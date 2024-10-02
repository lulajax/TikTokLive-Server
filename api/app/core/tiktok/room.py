from __future__ import annotations

import json
import os
from typing import TypeVar, Any, Literal

from TikTokLive.client.errors import UserOfflineError
from TikTokLive.client.web.web_settings import WebDefaults
from TikTokLive.events import Event, DisconnectEvent
from TikTokLive.events.base_event import BaseEvent
from betterproto import Casing
from pydantic import BaseModel, Field, ConfigDict
from starlette.websockets import WebSocket, WebSocketState

from app.core.tiktok.client import ChatSocketClient

WebDefaults.tiktok_sign_api_key = os.environ.get('SIGN_API_KEY')

E = TypeVar("E", bound="BaseEvent")


class RoomMessage(BaseModel):
    """Base data that must be provided with any event"""

    type: str
    unique_id: str
    data: Any = Field(default_factory=dict)


class TikTokEvent(RoomMessage):
    """Events forwarded from TikTok"""

    type: str = "tiktok_event"
    data: dict
    name: str


class ControlEvent(RoomMessage):
    """Events related to the control of the room itself"""

    type: str = "room_event"
    name: Literal["join", "leave", "end"]


class RoomClient(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ws: WebSocket
    id: str = Field(default_factory=lambda: os.urandom(16).hex())
    unique_id: str


class TikTokRoom:
    """
    A room represents a streamer's room. Multiple people can connect to a room.
    The room recycles a single TikTok connection for all clients for efficiency.

    """

    def __init__(self, unique_id: str, connection: ChatSocketClient):
        super().__init__()
        self._unique_id: str = unique_id
        self._connection: ChatSocketClient = connection
        self.__clients: dict[str, RoomClient] = {}
        self.register_events()

    @property
    def unique_id(self) -> str:
        """
        Return the unique ID of the room

        :return: The unique ID

        """

        return self._unique_id

    @property
    def _clients(self) -> dict[str, RoomClient]:
        """
        Return a copy of the clients safe to iterate over
        :return: The clients

        """

        return self.__clients.copy()

    def register_events(self) -> None:
        """
        Register all events from the connection

        :return: None

        """

        # noinspection PyProtectedMember
        from TikTokLive.events.proto_events import __all__ as proto_events

        # noinspection PyProtectedMember
        from TikTokLive.events.custom_events import __all__ as custom_events

        # All events
        from TikTokLive import events

        # Handler to forward the event
        async def event_forwarder(e: BaseEvent) -> None:

            for client in self._clients.values():
                data: dict = json.loads(e.to_json(casing=Casing.SNAKE)) if hasattr(e, 'to_json') else dict()
                name = e.get_type()
                print('recv', data)

                # Send the event over the WS
                await self._send_message(
                    ws=client.ws,
                    message=TikTokEvent(
                        name=name,
                        data=data,
                        unique_id=self._unique_id
                    )
                )

        # Forward all events
        for event_name in proto_events + custom_events:
            event = getattr(events, event_name)
            if hasattr(event, 'get_type'):
                self._connection.on(event, event_forwarder)

        # Custom handler for DisconnectEvent
        async def end_handler(_: Event) -> None:
            for client in self._clients.values():
                await self.leave(client=client, end=True)

        # Handle the disconnect event
        self._connection.on(DisconnectEvent, end_handler)

    @classmethod
    async def _send_message(cls, ws: WebSocket, message: RoomMessage) -> None:
        """
        Send a message to a WebSocket

        :param ws: The WebSocket to send the message to
        :param message: The message to send
        :return: None

        """

        if ws.client_state != WebSocketState.CONNECTED:
            return

        json_data: str = message.model_dump_json()
        await ws.send_text(json_data)

    @classmethod
    async def create(cls, unique_id: str) -> TikTokRoom:
        """
        Create a new room for the stream

        :param unique_id: The unique ID of the streamer
        :return: The room, or an error
        :raises: Exception if it fails to connect for whatever reason

        """

        # Create the client
        client: ChatSocketClient = ChatSocketClient(
            unique_id=unique_id
        )

        # Check if live
        if not await client.is_live(unique_id=unique_id):
            raise UserOfflineError("User is not live!")

        # Connect the client if live
        await client.start(process_connect_events=False, fetch_room_info=True)

        # Create the room
        return cls(
            unique_id=unique_id,
            connection=client
        )

    async def join(
            self,
            ws: WebSocket
    ) -> RoomClient:
        """
        Make a WebSocket join a room

        :param ws: The WebSocket connection
        :return: None

        """

        # Create the RoomClient wrapper & return it
        client: RoomClient = RoomClient(
            ws=ws,
            unique_id=self._unique_id
        )

        self.__clients[client.id] = client

        # Send the join message
        await self._send_message(
            ws=ws,
            message=ControlEvent(
                name="join",
                unique_id=self._unique_id
            )
        )

        return client

    async def leave(
            self,
            client: RoomClient,
            end: bool = False
    ) -> None:
        """
        Make a WebSocket leave a room

        :param client: The RoomClient wrapper
        :param end: Whether to send the message as an end message (the user is offline / we disconnected)
        :return: None

        """

        # Send the leave message
        await self._send_message(
            ws=client.ws,
            message=ControlEvent(
                name="leave" if not end else "end",
                unique_id=self._unique_id
            )
        )

        # Remove the client
        self.__clients.pop(client.id, None)

    @property
    def clients(self) -> int:
        """
        Return the # of clients in the room

        :return: The number of clients

        """

        return len(self._clients)

    async def kill(self) -> None:
        """
        Kill the room

        :return: None

        """

        # Make all clients leave
        for client in self._clients.values():
            await self.leave(client=client, end=True)

        # Disconnect the connection
        await self._connection.disconnect()

    def serialize(self) -> dict:
        """
        Serialize the room data as a preview

        :return: The serialized room

        """

        return {
            "unique_id": self._unique_id,
            "client_num": len(self._clients),
            "clients": [client.model_dump(exclude={"ws"}) for client in self._clients.values()],
            "is_connected": self._connection.connected
        }