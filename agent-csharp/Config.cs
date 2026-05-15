namespace AgentApp;

public class AgentConfig
{
    public string DeviceId { get; init; } = "MOCK-01";
    public string DeviceName { get; init; } = "장비 에이전트";
    public string DeviceType { get; init; } = "charger";
    public int Port { get; init; } = 8081;
    public string CentralBackendUrl { get; init; } = "http://localhost:8000";
    public string EquipmentHost { get; init; } = "192.168.1.10";
    public int EquipmentPort { get; init; } = 502;
    public bool UseMock { get; init; } = true;

    public static AgentConfig FromEnvironment() => new()
    {
        DeviceId = Environment.GetEnvironmentVariable("AGENT_DEVICE_ID") ?? "MOCK-01",
        DeviceName = Environment.GetEnvironmentVariable("AGENT_DEVICE_NAME") ?? "장비 에이전트",
        DeviceType = Environment.GetEnvironmentVariable("AGENT_DEVICE_TYPE") ?? "charger",
        Port = int.TryParse(Environment.GetEnvironmentVariable("AGENT_PORT"), out var port) ? port : 8081,
        CentralBackendUrl = Environment.GetEnvironmentVariable("CENTRAL_BACKEND_URL") ?? "http://localhost:8000",
        EquipmentHost = Environment.GetEnvironmentVariable("EQUIPMENT_HOST") ?? "192.168.1.10",
        EquipmentPort = int.TryParse(Environment.GetEnvironmentVariable("EQUIPMENT_PORT"), out var eqPort) ? eqPort : 502,
        UseMock = (Environment.GetEnvironmentVariable("USE_MOCK") ?? "true").ToLowerInvariant() != "false",
    };
}
