using System.Net.Http.Json;
using AgentApp.Models;

namespace AgentApp.Services;

public class CentralServerClient
{
    private readonly HttpClient _http;
    private readonly string _baseUrl;
    private readonly string _deviceId;

    public CentralServerClient(HttpClient http, AgentConfig config)
    {
        _http = http;
        _baseUrl = config.CentralBackendUrl.TrimEnd('/');
        _deviceId = config.DeviceId;
    }

    public async Task SendHeartbeatAsync(SensorData sensors, string status)
    {
        var payload = new HeartbeatPayload(
            DeviceId:    _deviceId,
            Status:      status,
            Temperature: sensors.Temperature,
            Voltage:     sensors.Voltage,
            Current:     sensors.Current
        );

        try
        {
            await _http.PostAsJsonAsync(
                $"{_baseUrl}/api/v1/equipment/devices/{_deviceId}/heartbeat",
                payload
            );
        }
        catch
        {
            // 중앙 서버 미응답 시 무시 - 다음 주기에 재시도
        }
    }

    public async Task ReportCommandResultAsync(string commandId, string status, string? errorMessage = null)
    {
        var result = new CommandResult(
            CommandId:    commandId,
            Status:       status,
            ErrorMessage: errorMessage
        );

        try
        {
            await _http.PostAsJsonAsync(
                $"{_baseUrl}/api/v1/equipment/commands/{commandId}/result",
                result
            );
        }
        catch
        {
            // 결과 전송 실패 시 무시
        }
    }

    public async Task ReportAnomalyAsync(string anomalyType, double value, double threshold)
    {
        var payload = new
        {
            device_id  = _deviceId,
            anomaly_type = anomalyType,
            value,
            threshold,
            detected_at = DateTime.UtcNow,
        };

        try
        {
            await _http.PostAsJsonAsync(
                $"{_baseUrl}/api/v1/equipment/devices/{_deviceId}/anomaly",
                payload
            );
        }
        catch
        {
            // 이상 감지 전송 실패 시 무시
        }
    }
}
