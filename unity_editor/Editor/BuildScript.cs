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
        string buildName = GetArg("-customBuildName") ?? "Game";
        bool cleanBuild = string.Equals(GetArg("-customCleanBuild"), "true", StringComparison.OrdinalIgnoreCase);

        if (string.IsNullOrEmpty(outputDir))
            throw new Exception("Missing -customBuildOutput argument");

        if (!string.IsNullOrEmpty(version))
            PlayerSettings.bundleVersion = version;

        BuildTarget target = string.IsNullOrEmpty(buildTargetArg)
            ? EditorUserBuildSettings.activeBuildTarget
            : (BuildTarget)Enum.Parse(typeof(BuildTarget), buildTargetArg);

        string locationPathName = GetOutputPath(target, outputDir, buildName);

        string[] scenes = EditorBuildSettings.scenes
            .Where(s => s.enabled)
            .Select(s => s.path)
            .ToArray();

        BuildPlayerOptions options = new BuildPlayerOptions
        {
            scenes = scenes,
            locationPathName = locationPathName,
            target = target,
            // CleanBuildCache discards Library/Bee (incremental player + IL2CPP
            // cache) but keeps the asset import cache. Requires Unity 2021.2+.
            options = cleanBuild ? BuildOptions.CleanBuildCache : BuildOptions.None,
        };

        Console.WriteLine($"Build starting: target={target}, version={version}, cleanBuild={cleanBuild}");

        var report = BuildPipeline.BuildPlayer(options);
        var summary = report.summary;

        Console.WriteLine($"Build result: {summary.result}, size: {summary.totalSize} bytes");

        if (summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
        {
            throw new Exception($"Build failed with result: {summary.result}");
        }
    }

    private static string GetOutputPath(BuildTarget target, string outputDir, string buildName)
    {
        switch (target)
        {
            case BuildTarget.StandaloneWindows64:
            case BuildTarget.StandaloneWindows:
                return System.IO.Path.Combine(outputDir, buildName + ".exe");
            case BuildTarget.StandaloneOSX:
                return System.IO.Path.Combine(outputDir, buildName + ".app");
            default:
                return System.IO.Path.Combine(outputDir, buildName);
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
