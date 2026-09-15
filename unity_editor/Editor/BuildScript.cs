// Copy this file into the Unity project at Assets/Editor/BuildScript.cs.
// Invoked by unity-build-bot via `-executeMethod BuildScript.PerformBuild`.
using System;
using System.Linq;
using UnityEditor;
using UnityEngine;

public static class BuildScript
{
    public static void PerformBuild()
    {
        string outputDir = GetArg("-customBuildOutput");
        string version = GetArg("-customBuildVersion");
        string buildTargetArg = GetArg("-buildTarget");

        if (string.IsNullOrEmpty(outputDir))
            throw new Exception("Missing -customBuildOutput argument");

        if (!string.IsNullOrEmpty(version))
            PlayerSettings.bundleVersion = version;

        BuildTarget target = string.IsNullOrEmpty(buildTargetArg)
            ? EditorUserBuildSettings.activeBuildTarget
            : (BuildTarget)Enum.Parse(typeof(BuildTarget), buildTargetArg);

        string locationPathName = GetOutputPath(target, outputDir);

        string[] scenes = EditorBuildSettings.scenes
            .Where(s => s.enabled)
            .Select(s => s.path)
            .ToArray();

        BuildPlayerOptions options = new BuildPlayerOptions
        {
            scenes = scenes,
            locationPathName = locationPathName,
            target = target,
            options = BuildOptions.None,
        };

        var report = BuildPipeline.BuildPlayer(options);
        var summary = report.summary;

        Console.WriteLine($"Build result: {summary.result}, size: {summary.totalSize} bytes");

        if (summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
        {
            throw new Exception($"Build failed with result: {summary.result}");
        }
    }

    private static string GetOutputPath(BuildTarget target, string outputDir)
    {
        switch (target)
        {
            case BuildTarget.StandaloneWindows64:
            case BuildTarget.StandaloneWindows:
                return System.IO.Path.Combine(outputDir, "Game.exe");
            case BuildTarget.StandaloneOSX:
                return System.IO.Path.Combine(outputDir, "Game.app");
            default:
                return System.IO.Path.Combine(outputDir, "Game");
        }
    }

    private static string GetArg(string name)
    {
        var args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == name)
                return args[i + 1];
        }
        return null;
    }
}
