"""
Inbound ports (driving ports) for the Analytics service.

Inbound ports define the use case interfaces that external callers use to
interact with the analytics domain. Each port represents a distinct capability
such as querying metrics, retrieving dashboards, or generating reports.
Adapters in the inbound layer (gRPC handlers, REST controllers, event
consumers) invoke these ports to fulfill client requests.
"""
