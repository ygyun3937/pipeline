namespace AgentApp.Models;

public record HeartbeatPayload(
    string DeviceId,
    string Status,
    double? Temperature,
    double? Voltage,
    double? Current
);
