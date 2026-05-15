namespace AgentApp.Models;

public record ExecuteRequest(
    string CommandId,
    string CommandType,
    Dictionary<string, object> Params
);
