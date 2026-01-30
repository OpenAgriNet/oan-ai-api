try:
    import pipecat.transports.base_transport as m
    import inspect
    print("BaseTransport init signature:")
    print(inspect.signature(m.BaseTransport.__init__))
except Exception as e:
    print(f"Error inspecting BaseTransport: {e}")

try:
    import pipecat.transports.base_input as m2
    import inspect
    print("BaseInputTransport init signature:")
    print(inspect.signature(m2.BaseInputTransport.__init__))
except Exception as e:
    print(f"Error inspecting BaseInputTransport: {e}")
