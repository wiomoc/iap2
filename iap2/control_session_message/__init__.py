__all__ = ["identification", "authentication", "eap", "vehicle_status"]

from enum import IntEnum
from struct import Struct
from typing import get_type_hints, NewType, get_args, get_origin, Annotated, Dict, Type, List, Optional

CSM_STRUCT = Struct(">HHH")
CSM_PARAM_STRUCT = Struct(">HH")
CSM_START = 0x4040

_MESSAGE_TYPES: Dict[int, Type] = dict()


def register_csm(csm_class):
    _MESSAGE_TYPES[csm_class.CSM_MSG_ID] = csm_class


async def read_csm(reader):
    start, length, msg_id = CSM_STRUCT.unpack(
        await reader.readexactly(6))
    if start != CSM_START:
        return
    payload = await reader.readexactly(length - 6)
    message_type = _MESSAGE_TYPES.get(msg_id)
    if message_type:
        message_instance = message_type()
        message_instance.csm_deserialize_params(payload)
        return message_instance
    else:
        return None


async def write_csm(writer, message):
    writer.write(message.csm_serialize())
    await writer.drain()


Int8 = NewType("Int8", int)
Int16 = NewType("Int16", int)
Int32 = NewType("Int32", int)
Int64 = NewType("Int64", int)
Uint8 = NewType("Uint8", int)
Uint16 = NewType("Uint16", int)
Uint32 = NewType("Uint32", int)
Uint64 = NewType("Uint64", int)
NoneLike = NewType("None", Optional[bool])


def csm(msg_id: int):
    def decorator(clazz):
        def build_deserialize_params(handlers):
            def deserialize_params(self, payload, handlers=handlers):
                while len(payload) > 0:
                    length, param_id = CSM_PARAM_STRUCT.unpack(
                        payload[:4])
                    param_payload = payload[4:length]
                    payload = payload[length:]
                    print(param_id)
                    tmp = handlers.get(param_id)
                    if tmp:
                        _serializer, deserializer, name, is_list = tmp
                        value = deserializer(param_payload)
                        if is_list:
                            value_list = getattr(self, name)
                            if not value_list:
                                value_list = []
                                setattr(self, name, value_list)
                            value_list.append(value)
                        else:
                            setattr(self, name, value)

            return deserialize_params

        def build_serialize_params(handlers):
            def serialize_params(self, handlers=handlers):
                params_bytes = bytearray()
                for param_id, (serializer, _deserializer, name, is_list) in handlers.items():
                    value = getattr(self, name)

                    if value is not None:
                        if is_list:
                            for val in value:
                                payload = serializer(val)
                                params_bytes.extend(CSM_PARAM_STRUCT.pack(
                                    len(payload) + 4, param_id) + payload)
                        else:
                            payload = serializer(value)
                            params_bytes.extend(CSM_PARAM_STRUCT.pack(
                                len(payload) + 4, param_id) + payload)
                return params_bytes

            return serialize_params

        def build_handlers(clazz):
            handlers = dict()
            hints = get_type_hints(clazz, include_extras=True).items()
            base_class = clazz.__base__
            if base_class != object and base_class is not None:
                extended_hints = []
                extended_hints.extend(get_type_hints(base_class, include_extras=True).items())
                extended_hints.extend(hints)
                hints = extended_hints

            for param_id, (name, hint) in enumerate(hints):
                is_list = False
                if get_origin(hint) == Annotated:
                    args = get_args(hint)
                    param_id = args[1]
                    hint = args[0]
                if get_origin(hint) == list:
                    is_list = True
                    args = get_args(hint)
                    hint = args[0]
                s = None
                if hint == bool:
                    s = Struct(">?")
                if hint == Int8:
                    s = Struct(">b")
                elif hint == Uint8:
                    s = Struct(">B")
                elif hint == Int16:
                    s = Struct(">h")
                elif hint == Uint16:
                    s = Struct(">H")
                elif hint == Int32:
                    s = Struct(">i")
                elif hint == Uint32:
                    s = Struct(">I")
                elif hint == Int64:
                    s = Struct(">q")
                elif hint == Uint64:
                    s = Struct(">Q")

                serializer = None
                deserializer = None
                if s is not None:
                    serializer = lambda val, struc=s: struc.pack(val)
                    deserializer = lambda buffer, struc=s: struc.unpack(buffer)[0] if len(buffer) > 0 else None
                elif hint == NoneLike or hint == type(None):
                    serializer = lambda val: b""
                    deserializer = lambda buffer: True
                elif issubclass(hint, IntEnum):
                    serializer = lambda val: bytes([val.value])
                    deserializer = lambda buffer, hint=hint: hint(buffer[0])
                elif hint == str:
                    serializer = lambda val: val.encode("utf-8") + b"\0"
                    deserializer = lambda buffer: buffer[:-1].decode("utf-8")
                elif hint == bytes:
                    serializer = lambda val: val
                    deserializer = lambda buffer: buffer
                elif isinstance(hint, type) and hint is not None:
                    group_handlers = build_handlers(hint)
                    serializer = build_serialize_params(group_handlers)

                    def de(buffer, de_params=build_deserialize_params(group_handlers), hint=hint):
                        instance = hint()
                        de_params(instance, buffer)
                        return instance

                    deserializer = de

                if not serializer:
                    raise TypeError("Invalid type for csm")

                handlers[param_id] = (serializer, deserializer, name, is_list)
            return handlers

        message_handlers = build_handlers(clazz)

        setattr(clazz, "csm_deserialize_params", build_deserialize_params(message_handlers))
        message_serialize_params = build_serialize_params(message_handlers)

        def serialize(self):
            params_bytes = message_serialize_params(self)
            header_bytes = CSM_STRUCT.pack(
                CSM_START,
                len(params_bytes) + 6, msg_id)
            return header_bytes + params_bytes

        setattr(clazz, "csm_serialize", serialize)
        setattr(clazz, "CSM_MSG_ID", msg_id)

        return clazz

    return decorator
