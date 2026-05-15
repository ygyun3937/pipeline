using AgentApp.Models;
using EasyModbus;

namespace AgentApp.Drivers;

public class ModbusTcpDriver : IHardwareDriver
{
    private readonly ModbusClient _client;
    private readonly string _host;
    private readonly int _port;

    // 레지스터 주소 상수
    private const int RegTemperature = 0x0001;
    private const int RegVoltage     = 0x0002;
    private const int RegCurrent     = 0x0003;
    private const int RegCmdCharge   = 0x0100;
    private const int RegCmdDisch    = 0x0101;
    private const int RegEstop       = 0x0200;
    private const int RegReset       = 0x0201;

    public ModbusTcpDriver(string host, int port)
    {
        _host = host;
        _port = port;
        _client = new ModbusClient(host, port);
    }

    public Task ConnectAsync()
    {
        _client.Connect();
        return Task.CompletedTask;
    }

    public Task DisconnectAsync()
    {
        _client.Disconnect();
        return Task.CompletedTask;
    }

    public Task<SensorData> ReadSensorsAsync()
    {
        int[] regs = _client.ReadHoldingRegisters(RegTemperature, 3);
        var data = new SensorData(
            Temperature: regs[0] / 10.0,
            Voltage:     regs[1] / 1000.0,
            Current:     regs[2] / 1000.0,
            MeasuredAt:  DateTime.UtcNow
        );
        return Task.FromResult(data);
    }

    public Task ExecuteCommandAsync(string commandType, Dictionary<string, object> parameters)
    {
        switch (commandType)
        {
            case "charge":
                int targetVoltage = parameters.TryGetValue("target_voltage", out var tv)
                    ? Convert.ToInt32(tv) : 4200;
                _client.WriteSingleRegister(RegCmdCharge, targetVoltage);
                break;
            case "discharge":
                _client.WriteSingleRegister(RegCmdDisch, 1);
                break;
            case "reset":
                _client.WriteSingleRegister(RegReset, 1);
                break;
            default:
                throw new ArgumentException($"Unknown command type: {commandType}");
        }
        return Task.CompletedTask;
    }

    public Task EmergencyStopAsync()
    {
        _client.WriteSingleRegister(RegEstop, 0x01);
        return Task.CompletedTask;
    }
}
