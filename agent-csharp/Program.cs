using AgentApp;
using AgentApp.Drivers;
using AgentApp.Models;
using AgentApp.Services;

var config = AgentConfig.FromEnvironment();
var builder = WebApplication.CreateBuilder(args);

// DI 등록
builder.Services.AddSingleton(config);
builder.Services.AddSingleton<IHardwareDriver>(_ =>
    config.UseMock
        ? new MockDriver()
        : new ModbusTcpDriver(config.EquipmentHost, config.EquipmentPort));
builder.Services.AddHttpClient<CentralServerClient>();
builder.Services.AddSingleton<HeartbeatBackgroundService>();
builder.Services.AddHostedService(sp => sp.GetRequiredService<HeartbeatBackgroundService>());

var app = builder.Build();

// 현재 장비 상태 (HeartbeatBackgroundService를 통해 공유)
var heartbeat = app.Services.GetRequiredService<HeartbeatBackgroundService>();

// 실행 중인 커맨드 태스크 추적
var commandLock = new SemaphoreSlim(1, 1);
Task? currentTask = null;
CancellationTokenSource? currentCts = null;

// POST /execute
app.MapPost("/execute", async (ExecuteRequest req, IHardwareDriver driver, CentralServerClient client) =>
{
    await commandLock.WaitAsync();
    try
    {
        // 이전 태스크 취소
        if (currentCts is not null)
        {
            await currentCts.CancelAsync();
            currentCts.Dispose();
        }

        heartbeat.DeviceStatus = "running";
        var cts = new CancellationTokenSource();
        currentCts = cts;

        currentTask = Task.Run(async () =>
        {
            try
            {
                await driver.ExecuteCommandAsync(req.CommandType, req.Params);

                if (!cts.IsCancellationRequested)
                {
                    heartbeat.DeviceStatus = "done";
                    await client.ReportCommandResultAsync(req.CommandId, "done");
                }
            }
            catch (OperationCanceledException)
            {
                // estop 또는 새 커맨드로 취소됨
            }
            catch (Exception ex)
            {
                heartbeat.DeviceStatus = "error";
                await client.ReportCommandResultAsync(req.CommandId, "error", ex.Message);
            }
        }, cts.Token);
    }
    finally
    {
        commandLock.Release();
    }

    return Results.Ok(new { status = "started", command_id = req.CommandId });
});

// POST /pause
app.MapPost("/pause", () =>
{
    heartbeat.DeviceStatus = "paused";
    return Results.Ok(new { status = "paused" });
});

// POST /resume
app.MapPost("/resume", () =>
{
    heartbeat.DeviceStatus = "running";
    return Results.Ok(new { status = "running" });
});

// POST /estop
app.MapPost("/estop", async (EstopRequest req, IHardwareDriver driver) =>
{
    await commandLock.WaitAsync();
    try
    {
        if (currentCts is not null)
        {
            await currentCts.CancelAsync();
            currentCts.Dispose();
            currentCts = null;
        }
        heartbeat.DeviceStatus = "estop";
    }
    finally
    {
        commandLock.Release();
    }

    await driver.EmergencyStopAsync();
    return Results.Ok(new { status = "estop", reason = req.Reason });
});

// POST /reset
app.MapPost("/reset", () =>
{
    heartbeat.DeviceStatus = "idle";
    return Results.Ok(new { status = "idle" });
});

// GET /status
app.MapGet("/status", (IHardwareDriver driver) =>
    Results.Ok(new
    {
        device_id = config.DeviceId,
        status    = heartbeat.DeviceStatus,
    })
);

app.Run($"http://0.0.0.0:{config.Port}");

// EstopRequest는 Models에 없으므로 Program.cs 내부에 정의
public record EstopRequest(string Reason = "");
