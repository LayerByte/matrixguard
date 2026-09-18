from __future__ import annotations
import asyncio,json,logging,os,sqlite3
from collections import defaultdict,deque
from datetime import UTC,datetime,timedelta
from nio import AsyncClient,AsyncClientConfig,InviteMemberEvent,JoinError,LoginResponse,MatrixRoom,RoomMemberEvent,RoomMessageText

LOGGER=logging.getLogger("matrixguard")

class Store:
    def __init__(self,path:str)->None:
        self.db=sqlite3.connect(path);self.db.execute("CREATE TABLE IF NOT EXISTS warnings(id INTEGER PRIMARY KEY AUTOINCREMENT,room_id TEXT NOT NULL,user_id TEXT NOT NULL,moderator_id TEXT NOT NULL,reason TEXT NOT NULL,created_at TEXT NOT NULL)");self.db.execute("CREATE TABLE IF NOT EXISTS settings(room_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(room_id,key))");self.db.commit()
    def warn(self,room:str,user:str,mod:str,reason:str)->int:cur=self.db.execute("INSERT INTO warnings(room_id,user_id,moderator_id,reason,created_at) VALUES(?,?,?,?,?)",(room,user,mod,reason[:1000],datetime.now(UTC).isoformat()));self.db.commit();return int(cur.lastrowid)
    def warnings(self,room:str,user:str):return self.db.execute("SELECT id,reason FROM warnings WHERE room_id=? AND user_id=? ORDER BY id DESC LIMIT 20",(room,user)).fetchall()
    def get(self,room:str,key:str,default:str="")->str:row=self.db.execute("SELECT value FROM settings WHERE room_id=? AND key=?",(room,key)).fetchone();return row[0] if row else default
    def set(self,room:str,key:str,value:str)->None:self.db.execute("INSERT INTO settings VALUES(?,?,?) ON CONFLICT(room_id,key) DO UPDATE SET value=excluded.value",(room,key,value));self.db.commit()
    def close(self)->None:self.db.close()

class MatrixGuard:
    def __init__(self)->None:
        self.homeserver=os.getenv("MATRIX_HOMESERVER","").rstrip("/");self.user=os.getenv("MATRIX_USER_ID","").strip();self.token=os.getenv("MATRIX_ACCESS_TOKEN","").strip()
        if not self.homeserver or not self.user or not self.token:raise RuntimeError("MATRIX_HOMESERVER, MATRIX_USER_ID, and MATRIX_ACCESS_TOKEN are required")
        self.store=Store(os.getenv("DATABASE_PATH","matrixguard.db"));self.rules=os.getenv("ROOM_RULES","Be respectful. No spam or abusive content.");self.spam=max(3,int(os.getenv("SPAM_MESSAGES","6")));self.window=max(2,int(os.getenv("SPAM_WINDOW_SECONDS","8")));self.phrases=tuple(p.strip().lower() for p in os.getenv("BLOCKED_PHRASES","").split(",") if p.strip());self.times=defaultdict(deque);self.last=defaultdict(lambda:deque(maxlen=3))
        self.client=AsyncClient(self.homeserver,self.user,config=AsyncClientConfig(max_limit_exceeded=0,max_timeouts=0));self.client.access_token=self.token;self.client.user_id=self.user
    async def send(self,room:str,text:str)->None:
        response=await self.client.room_send(room,"m.room.message",{"msgtype":"m.notice","body":text})
        if response.__class__.__name__.endswith("Error"):LOGGER.warning("message_send_failed",extra={"room_id":room,"response":str(response)})
    async def power(self,room:MatrixRoom,user_id:str)->int:
        response=await self.client.room_get_state_event(room.room_id,"m.room.power_levels","")
        content=getattr(response,"content",{}) or {};return int((content.get("users") or {}).get(user_id,content.get("users_default",0)))
    async def redact(self,room:MatrixRoom,event:RoomMessageText,reason:str)->None:
        response=await self.client.room_redact(room.room_id,event.event_id,reason=reason)
        if response.__class__.__name__.endswith("Error"):LOGGER.warning("redaction_failed",extra={"room_id":room.room_id,"event_id":event.event_id})
    async def on_invite(self,room:MatrixRoom,event:InviteMemberEvent)->None:
        if event.state_key==self.user:
            response=await self.client.join(room.room_id)
            if isinstance(response,JoinError):LOGGER.error("room_join_failed",extra={"room_id":room.room_id,"response":str(response)})
    async def on_member(self,room:MatrixRoom,event:RoomMemberEvent)->None:
        membership=event.membership
        if event.state_key==self.user:return
        if membership=="join" and event.prev_content.get("membership")!="join":await self.send(room.room_id,f"Welcome {event.state_key}. Use !rules before participating.")
    async def on_message(self,room:MatrixRoom,event:RoomMessageText)->None:
        if event.sender==self.user:return
        body=event.body.strip();is_mod=await self.power(room,event.sender)>=50
        if body.startswith("!"):await self.command(room,event,is_mod);return
        if is_mod:return
        key=(room.room_id,event.sender);now=datetime.now(UTC);queue=self.times[key];queue.append(now);cutoff=now-timedelta(seconds=self.window)
        while queue and queue[0]<cutoff:queue.popleft()
        recent=self.last[key];recent.append(body.lower());reason=None
        if len(queue)>=self.spam:reason="message flood"
        elif len(recent)==recent.maxlen and len(set(recent))==1:reason="repeated messages"
        elif any(phrase in body.lower() for phrase in self.phrases):reason="blocked phrase"
        if reason:await self.redact(room,event,reason);LOGGER.info("automatic_redaction",extra={"room_id":room.room_id,"sender":event.sender,"reason":reason})
    async def command(self,room:MatrixRoom,event:RoomMessageText,is_mod:bool)->None:
        parts=event.body.split(maxsplit=2);command=parts[0].lower()
        if command=="!rules":await self.send(room.room_id,self.store.get(room.room_id,"rules",self.rules));return
        if not is_mod:await self.send(room.room_id,"This command requires sufficient Matrix room power.");return
        if command=="!setrules" and len(parts)>1:self.store.set(room.room_id,"rules",event.body.split(maxsplit=1)[1]);await self.send(room.room_id,"Room rules updated.")
        elif command=="!warn" and len(parts)>1:
            target=parts[1];reason=parts[2] if len(parts)>2 else "No reason provided";warning_id=self.store.warn(room.room_id,target,event.sender,reason);await self.send(room.room_id,f"Warning #{warning_id} issued to {target}: {reason}")
        elif command=="!warnings" and len(parts)>1:
            rows=self.store.warnings(room.room_id,parts[1]);await self.send(room.room_id,"\n".join(f"#{row[0]} {row[1]}" for row in rows) or "No warnings.")
        elif command in {"!kick","!ban"} and len(parts)>1:
            target=parts[1];reason=parts[2] if len(parts)>2 else "Moderation action"
            response=await (self.client.room_kick(room.room_id,target,reason) if command=="!kick" else self.client.room_ban(room.room_id,target,reason))
            if response.__class__.__name__.endswith("Error"):await self.send(room.room_id,"Moderation action failed. Check bot power levels.")
            else:await self.send(room.room_id,f"{target} was {command[1:]}ed.")
        else:await self.send(room.room_id,"Commands: !rules, !setrules, !warn <user> [reason], !warnings <user>, !kick <user>, !ban <user>")
    async def run(self)->None:
        self.client.add_event_callback(self.on_invite,InviteMemberEvent);self.client.add_event_callback(self.on_member,RoomMemberEvent);self.client.add_event_callback(self.on_message,RoomMessageText);LOGGER.info("startup",extra={"user_id":self.user})
        try:await self.client.sync_forever(timeout=30000,full_state=True)
        finally:self.store.close();await self.client.close();LOGGER.info("shutdown")

def run()->None:
    logging.basicConfig(level=logging.INFO,format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}');asyncio.run(MatrixGuard().run())
