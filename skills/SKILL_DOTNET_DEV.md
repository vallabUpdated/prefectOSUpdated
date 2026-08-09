---
name: .NET Development
description: C# / .NET application development — ASP.NET Core, Entity Framework, solution structure, NuGet.
keywords: .net, dotnet, c#, csharp, asp.net, aspnet, blazor, razor, entity framework, ef core, nuget, wpf, maui, xamarin, linq
stages: plan, spec, env, execute, test
---

# Skill: .NET Development

You are proficient in modern .NET (8+) and C#. Apply these guidelines whenever the task involves the .NET stack.

## Code Style
- Follow standard C# conventions: PascalCase for types/methods/properties, camelCase for locals/parameters, `_camelCase` for private fields.
- Enable nullable reference types (`<Nullable>enable</Nullable>`) and treat warnings seriously.
- Prefer `async`/`await` end-to-end for I/O; never block with `.Result` or `.Wait()`.
- Use dependency injection via the built-in container; register services in `Program.cs`.

## Project Structure
- One solution (`.sln`) with clearly separated projects: `MyApp.Web`, `MyApp.Core` (domain), `MyApp.Infrastructure` (data access), `MyApp.Tests`.
- Configuration via `appsettings.json` + environment overrides; secrets via user-secrets or environment variables, never committed.

## Frameworks
- **ASP.NET Core**: minimal APIs for small services, MVC/controllers for larger apps; model validation with data annotations or FluentValidation.
- **Entity Framework Core**: code-first with migrations; `DbContext` scoped per request; avoid N+1 queries with `.Include()` deliberately.
- **Blazor**: component-per-file, parameters via `[Parameter]`, state in scoped services.

## Environment
- Generated setup scripts should use the `dotnet` CLI: `dotnet new`, `dotnet restore`, `dotnet build`, `dotnet run`.
- Target the LTS SDK unless the user asks otherwise; state the required SDK version in the plan.
