using System.Diagnostics;

var projectRoot = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
var batchPath = Path.Combine(projectRoot, "启动 YuReader.bat");

if (!File.Exists(batchPath))
{
    return;
}

var startInfo = new ProcessStartInfo
{
    FileName = Environment.GetEnvironmentVariable("ComSpec") ?? "cmd.exe",
    Arguments = "/d /c \"\"" + batchPath + "\"\"",
    WorkingDirectory = projectRoot,
    UseShellExecute = false,
    CreateNoWindow = true,
    WindowStyle = ProcessWindowStyle.Hidden
};

try
{
    Process.Start(startInfo);
}
catch
{
    // The batch file remains the fallback launcher when the wrapper cannot start.
}
