from typing import Annotated

from iap2.control_session_message import csm, Uint16, Int16


@csm(0xA100)
class StartVehicleStatusUpdates:
    pass


@csm(0xA101)
class VehicleStatusUpdate:
    range: Annotated[Uint16, 3]
    outside_temperature: Annotated[Int16, 4]
    range_warning: Annotated[bool, 5]


@csm(0xA102)
class StopVehicleStatusUpdates:
    pass
