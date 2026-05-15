using AgentApp.Drivers;

namespace AgentApp.Services;

public class HeartbeatBackgroundService : BackgroundService
{
    private const double TempMax = 45.0;
    private const double VoltMax = 4.25;
    private const double CurrMax = 3.0;

    private readonly IHardwareDriver _driver;
    private readonly CentralServerClient _client;
    private readonly ILogger<HeartbeatBackgroundService> _logger;

    // 현재 장비 상태를 외부(Program.cs)에서 읽을 수 있도록 공유
    public string DeviceStatus { get; set; } = "idle";

    public HeartbeatBackgroundService(
        IHardwareDriver driver,
        CentralServerClient client,
        ILogger<HeartbeatBackgroundService> logger)
    {
        _driver = driver;
        _client = client;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var sensors = await _driver.ReadSensorsAsync();

                await _client.SendHeartbeatAsync(sensors, DeviceStatus);

                // 임계값 초과 감지
                if (sensors.Temperature > TempMax)
                    await _client.ReportAnomalyAsync("over_temperature", sensors.Temperature, TempMax);

                if (sensors.Voltage > VoltMax)
                    await _client.ReportAnomalyAsync("over_voltage", sensors.Voltage, VoltMax);

                if (Math.Abs(sensors.Current) > CurrMax)
                    await _client.ReportAnomalyAsync("over_current", Math.Abs(sensors.Current), CurrMax);
            }
            catch (Exception ex)
            {
                // 실패해도 서비스 계속 실행
                _logger.LogWarning(ex, "Heartbeat cycle failed, continuing...");
            }

            await Task.Delay(TimeSpan.FromSeconds(5), stoppingToken);
        }
    }
}
