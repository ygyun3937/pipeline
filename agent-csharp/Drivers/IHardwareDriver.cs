using AgentApp.Models;

namespace AgentApp.Drivers;

public interface IHardwareDriver
{
    Task ConnectAsync();
    Task DisconnectAsync();
    Task<SensorData> ReadSensorsAsync();
    Task ExecuteCommandAsync(string commandType, Dictionary<string, object> parameters);
    Task EmergencyStopAsync();
}
