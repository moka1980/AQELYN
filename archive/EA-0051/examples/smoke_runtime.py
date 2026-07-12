from aqelyn.kernel import AQELYNKernel
from aqelyn.event_bus import InMemoryEventBus, AQELYNEvent

kernel = AQELYNKernel()
event_bus = InMemoryEventBus()
kernel.register(event_bus)
kernel.start()

event_bus.publish(AQELYNEvent(type="AQELYN.RuntimeStarted", payload={"status": "ok"}))

assert kernel.health().status == "healthy"
kernel.stop()