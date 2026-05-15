using AgentApp.Models;

namespace AgentApp.Drivers;

/// <summary>
/// 시뮬레이션 드라이버 - USE_MOCK=true 시 사용. 실제 하드웨어 없이 테스트 가능.
/// </summary>
public class MockDriver : IHardwareDriver
{
    private readonly Random _rng = new();

    // 내부 상태
    private double _voltage = 0.0;
    private double _current = 0.0;
    private double _temperature = 25.0;

    public Task ConnectAsync() => Task.CompletedTask;

    public Task DisconnectAsync() => Task.CompletedTask;

    public Task<SensorData> ReadSensorsAsync()
    {
        var data = new SensorData(
            Temperature: _temperature,
            Voltage:     _voltage,
            Current:     _current,
            MeasuredAt:  DateTime.UtcNow
        );
        return Task.FromResult(data);
    }

    public async Task ExecuteCommandAsync(string commandType, Dictionary<string, object> parameters)
    {
        switch (commandType)
        {
            case "charge":
            {
                // voltage 서서히 증가, 5초 대기 (10 steps * 500ms)
                const int steps = 10;
                double targetVoltage = parameters.TryGetValue("target_voltage", out var tv)
                    ? Convert.ToDouble(tv) / 1000.0 : 4.2;
                double startVoltage = _voltage;
                _current = parameters.TryGetValue("current", out var curr) ? Convert.ToDouble(curr) : 1.0;

                for (int i = 1; i <= steps; i++)
                {
                    await Task.Delay(500);
                    _voltage = Math.Round(startVoltage + i * ((targetVoltage - startVoltage) / steps), 3);
                }
                _current = 0.0;
                break;
            }
            case "discharge":
            {
                // voltage 서서히 감소, 5초 대기 (10 steps * 500ms)
                const int steps = 10;
                const double cutoffVoltage = 2.8;
                double startVoltage = _voltage > 0 ? _voltage : 4.2;
                _current = -(Math.Abs(parameters.TryGetValue("current", out var curr) ? Convert.ToDouble(curr) : 1.0));

                for (int i = 1; i <= steps; i++)
                {
                    await Task.Delay(500);
                    _voltage = Math.Round(startVoltage - i * ((startVoltage - cutoffVoltage) / steps), 3);
                }
                _current = 0.0;
                break;
            }
            case "measure":
            {
                // 랜덤 센서값, 2초 대기
                await Task.Delay(2000);
                _temperature = Math.Round(25.0 + _rng.NextDouble() * 7 - 2, 2);
                _voltage = Math.Round(2.8 + _rng.NextDouble() * 1.4, 3);
                _current = Math.Round(_rng.NextDouble() * 4 - 2, 3);
                break;
            }
            case "reset":
            {
                // 초기화, 1초 대기
                await Task.Delay(1000);
                _voltage = 0.0;
                _current = 0.0;
                _temperature = 25.0;
                break;
            }
            default:
                throw new ArgumentException($"Unknown command type: {commandType}");
        }
    }

    public Task EmergencyStopAsync()
    {
        _current = 0.0;
        return Task.CompletedTask;
    }
}
