import sqlite3 as sl
from pydantic import BaseModel
from starlette.templating import Jinja2Templates
from starlette.requests import Request
import json
from datetime import datetime
from typing import List
from fastapi import FastAPI
import asyncio
from starlette.websockets import WebSocket, WebSocketDisconnect

database = 'notifications.db'
con = sl.connect(database)
with con:
    con.execute(
        "CREATE TABLE IF NOT EXISTS notifications_db (id integer primary key, type varchar, title varchar, content varchar, lastSentAt datetime);")
con.close()


def suka_convert(sql_result):
    result = []
    for i in sql_result:
        result.append({"id": i[0], "type": i[1], "title": i[2], "content": i[3], "lastSentAt": i[4]})
    return result


class Data_Create(BaseModel):
    id: int
    type: str
    title: str
    content: str


class Data_Edit(BaseModel):
    type: str
    title: str
    content: str


app = FastAPI()


class Notifier:
    def __init__(self):
        self.connections: List[WebSocket] = []
        self.generator = self.get_notification_generator()

    async def get_notification_generator(self):
        while True:
            message = yield
            await self._notify(message)

    async def push(self, msg):
        await self.generator.asend(msg)

    async def push_delay(self, msg, delay):
        await asyncio.sleep(delay)
        await self.generator.asend(msg)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.connections.append(websocket)

    def remove(self, websocket: WebSocket):
        self.connections.remove(websocket)

    async def _notify(self, message):
        living_connections = []
        while len(self.connections) > 0:
            websocket = self.connections.pop()
            await websocket.send_json(message)
            living_connections.append(websocket)
        self.connections = living_connections


notifier = Notifier()

templates = Jinja2Templates(directory="templates")


@app.get("/api/notifications")
async def get():
    con = sl.connect(database)
    with con: data = con.execute("SELECT * FROM notifications_db;").fetchall()
    con.close()
    return json.dumps(suka_convert(data))


@app.post("/api/notifications")
async def post_create(recieved: Data_Create):
    recieved_data = list(dict(recieved).values())
    con = sl.connect(database)
    with con:
        data = con.execute("SELECT * FROM notifications_db;").fetchall()

    for i in data:
        if i[0] == recieved_data[0]:
            con.close()
            return 'Уведомление с таким id уже существует'
    with con:
        con.execute(
            f'insert into notifications_db (id, type, title, content) values ({recieved_data[0]}, "{recieved_data[1]}", "{recieved_data[2]}", "{recieved_data[3]}");')
    con.close()
    return 'Уведомление успешно создано'


@app.put("/api/notifications/{notification_id}")
async def put_edit(notification_id: int, recieved: Data_Edit):
    recieved_data = list(dict(recieved).values())
    con = sl.connect(database)
    with con:
        data = con.execute("SELECT * FROM notifications_db;").fetchall()

    for i in data:
        if i[0] == notification_id:
            with con: con.execute(
                f'update notifications_db set type = "{recieved_data[0] if i[1] != recieved_data[0] else i[1]}", title = "{recieved_data[1] if i[2] != recieved_data[1] else i[2]}", content = "{recieved_data[2] if i[3] != recieved_data[2] else i[3]}" where id = {notification_id};')
            con.close()
            return 'Уведомление успешно изменено'
    con.close()
    return 'Уведомления с данным id не существует'


@app.delete("/api/notifications/{notification_id}")
async def delete_notification(notification_id: int):
    con = sl.connect(database)
    with con:
        data = con.execute("SELECT * FROM notifications_db;").fetchall()

    for i in data:
        if i[0] == notification_id:
            with con: con.execute(f'delete from notifications_db where id = {notification_id}')
            con.close()
            return 'Уведомление успешно удалено'
    con.close()
    return 'Уведомления с данным id не существует'


@app.get("/api/notifications/{notification_id}/send")
async def send_notification(notification_id: int):
    con = sl.connect(database)
    with con:
        data = con.execute(f'SELECT * FROM notifications_db WHERE id = {notification_id};').fetchall()
        con.execute(f'update notifications_db set lastSentAt = "{datetime.now()}" where id ={notification_id}')
        data = suka_convert(data)
    con.close()
    await notifier.push(data[0])
    return data


@app.get("/api/notifications/{notification_id}/send/h/{h}/m/{m}/s/{s}")
async def send_notification_delay(notification_id: int, h: int, m: int, s: int):
    con = sl.connect(database)
    with con:
        data = con.execute(f'SELECT * FROM notifications_db WHERE id = {notification_id};').fetchall()
        data = suka_convert(data)
    con.close()
    await notifier.push_delay(data[0], h*60*60+m*60+s)
    return json.dumps(data)


@app.get("/")
async def login(request: Request):
    return templates.TemplateResponse("user.html", {'request': request})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    async def message_await():
        data = await websocket.receive_json()
        print(data)
        await notifier.push(data)

    await notifier.connect(websocket)
    id = websocket.__hash__()
    print(id)
    await websocket.send_json({"client_id": id})
    try:
        while True:
            try:
                await websocket.send_json({"id": "server", "message": "ping"})
                brusko = await asyncio.wait_for(websocket.receive_json(), timeout=5)
                print('brusko', brusko)
                if brusko == {"id": id, "message": "pong"}:
                    try:
                        await asyncio.wait_for(message_await(), timeout=2)
                    except asyncio.TimeoutError:
                        pass
                else:
                    print('pong fail')
                    raise WebSocketDisconnect
            except asyncio.TimeoutError:
                raise WebSocketDisconnect

    except WebSocketDisconnect:
        notifier.remove(websocket)


@app.on_event("startup")
async def startup():
    await notifier.generator.asend(None)
