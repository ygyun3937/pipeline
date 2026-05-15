namespace AgentApp.Models;

public record SensorData(
    double Temperature,
    double Voltage,
    double Current,
    DateTime MeasuredAt
);
