namespace AgentApp.Models;

public record CommandResult(
    string CommandId,
    string Status,        // "done" | "error"
    string? ErrorMessage
);
