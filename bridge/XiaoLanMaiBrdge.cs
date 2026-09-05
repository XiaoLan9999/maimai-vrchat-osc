using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading;
using HarmonyLib;
using Manager;
using MelonLoader;

[assembly: MelonInfo(typeof(MaiDGBridge.BridgeMod), "XiaoLanMaiBrdge", "1.4.18", "XiaoLan9999", "")]
[assembly: MelonGame("sega-interactive", "Sinmai")]

namespace MaiDGBridge
{
    public sealed class BridgeMod : MelonMod
    {
        private const int GameplayMetricsIntervalMs = 1000;
        private const int GameplayMetricsWarmupMs = 3000;
        private const int IdlePresenceIntervalMs = 1000;
        private const int UserNameRetryIntervalMs = 1000;
        private const int SlowPathLogIntervalMs = 5000;
        private const double SlowPathThresholdMs = 8.0;
        private const string InstanceSemaphoreName = "XiaoLanMaiBrdge.Singleton";
        private static readonly object MemberCacheLock = new object();
        private static readonly Dictionary<System.Type, Dictionary<string, MemberInfo>> InstanceMemberCache =
            new Dictionary<System.Type, Dictionary<string, MemberInfo>>();
        private static readonly Dictionary<System.Type, Dictionary<string, MemberInfo>> StaticMemberCache =
            new Dictionary<System.Type, Dictionary<string, MemberInfo>>();
        private static readonly Dictionary<MethodCacheKey, MethodInfo> MethodCache =
            new Dictionary<MethodCacheKey, MethodInfo>();
        private static readonly Dictionary<System.Type, PropertyInfo> IntegerIndexerCache =
            new Dictionary<System.Type, PropertyInfo>();
        private readonly Snapshot[] _last = new Snapshot[2];
        private readonly Snapshot[] _hookCounts = new Snapshot[2];
        private readonly bool[] _judgePublishPending = new bool[2];
        private readonly Snapshot[] _lastResult = new Snapshot[2];
        private readonly Snapshot[] _finalGameplay = new Snapshot[2];
        private Snapshot _selectedMetadata;
        private PresenceSnapshot _selectedPresenceMetadata;
        private int _selectedPresenceRequestedDifficulty = -1;
        private readonly Stopwatch _clock = Stopwatch.StartNew();
        private static BridgeMod _active;
        private static object _advertiseProcess;
        private static object _entryProcess;
        private static object _modeSelectProcess;
        private static object _mapSelectProcess;
        private static object _ticketSelectProcess;
        private static object _characterSelectProcess;
        private static object _transitionProcess;
        private static string _transitionStatus;
        private static object _musicSelectProcess;
        private static object _resultProcess;
        private static bool _sessionStarted;
        private SseServer _server;
        private Semaphore _instanceSemaphore;
        private bool _ownsInstanceSemaphore;
        private bool _wasInGame;
        private bool _judgeHookObserved;
        private bool _metadataWarningLogged;
        private bool _gameplayMetricsWarningLogged;
        private bool _gameplayTimeResolved;
        private bool _presenceRefreshRequested = true;
        private bool _resultRefreshRequested;
        private MethodInfo _notesManagerInstanceMethod;
        private MethodInfo _notesCurrentMsecMethod;
        private MethodInfo _notesPlayFirstMsecMethod;
        private MethodInfo _notesPlayFinalMsecMethod;
        private string _cachedVersion = string.Empty;
        private string _cachedUserName = string.Empty;
        private long _lastPresencePublish;
        private long _lastUserNameRead;
        private long _lastResultPublish;
        private long _lastJudgePublish;
        private long _lastGameplayMetricsCapture;
        private long _gameplayMetricsReadyAt;
        private long _lastErrorLog;
        private long _lastSlowUpdateLog;
        private long _lastSlowMetricsLog;
        private long _lastSlowJudgeLog;
        private long _resultHoldUntil;
        private int _publishIntervalMs = 250;
        private int _presenceIntervalMs = 250;

        private struct MethodCacheKey : IEquatable<MethodCacheKey>
        {
            private readonly System.Type _type;
            private readonly string _name;
            private readonly bool _isStatic;
            private readonly int _argumentCount;
            private readonly System.Type _argument0;
            private readonly System.Type _argument1;

            public MethodCacheKey(
                System.Type type,
                string name,
                bool isStatic,
                int argumentCount,
                System.Type argument0,
                System.Type argument1)
            {
                _type = type;
                _name = name;
                _isStatic = isStatic;
                _argumentCount = argumentCount;
                _argument0 = argument0;
                _argument1 = argument1;
            }

            public bool Equals(MethodCacheKey other)
            {
                return ReferenceEquals(_type, other._type) &&
                       string.Equals(_name, other._name, StringComparison.Ordinal) &&
                       _isStatic == other._isStatic &&
                       _argumentCount == other._argumentCount &&
                       ReferenceEquals(_argument0, other._argument0) &&
                       ReferenceEquals(_argument1, other._argument1);
            }

            public override bool Equals(object value)
            {
                return value is MethodCacheKey && Equals((MethodCacheKey)value);
            }

            public override int GetHashCode()
            {
                unchecked
                {
                    int hash = _type == null ? 0 : _type.GetHashCode();
                    hash = (hash * 397) ^ (_name == null ? 0 : _name.GetHashCode());
                    hash = (hash * 397) ^ (_isStatic ? 1 : 0);
                    hash = (hash * 397) ^ _argumentCount;
                    hash = (hash * 397) ^ (_argument0 == null ? 0 : _argument0.GetHashCode());
                    return (hash * 397) ^ (_argument1 == null ? 0 : _argument1.GetHashCode());
                }
            }
        }

        public override void OnInitializeMelon()
        {
            BridgeConfig config = BridgeConfig.Load(Path.Combine(Environment.CurrentDirectory, "XiaoLanMaiBrdge.ini"));
            _publishIntervalMs = config.PublishIntervalMs;
            _presenceIntervalMs = config.PresenceIntervalMs;

            if (!config.Enabled)
            {
                MelonLogger.Msg("XiaoLanMaiBrdge is disabled by XiaoLanMaiBrdge.ini");
                return;
            }

            if (!TryAcquireInstance())
            {
                MelonLogger.Warning("XiaoLanMaiBrdge duplicate instance ignored; remove old bridge DLLs from Mods");
                return;
            }

            _active = this;

            try
            {
                _server = new SseServer(config.Port);
                _server.Start();
                PatchJudgeResults();
                PatchAdvertiseProcesses();
                PatchEntryProcess();
                PatchModeSelectProcess();
                PatchAuxiliaryPresenceProcesses();
                PatchMusicSelect();
                PatchResultProcess();
                ResolveGameplayTimeMethods();
                MelonLogger.Msg("XiaoLanMaiBrdge listening on http://127.0.0.1:" + config.Port + "/events");
            }
            catch (Exception ex)
            {
                MelonLogger.Error("XiaoLanMaiBrdge failed to start: " + ex.Message);
                _server = null;
            }
        }

        public override void OnUpdate()
        {
            if (_server == null || !_server.IsRunning)
            {
                return;
            }

            long updateStarted = Stopwatch.GetTimestamp();
            try
            {
                bool inGame = GameManager.IsInGame;
                long now = _clock.ElapsedMilliseconds;

                bool gameplayJustEnded = !inGame && _wasInGame;
                if (_resultProcess != null && !gameplayJustEnded && ShouldCaptureResult(now))
                {
                    CaptureResultEvents(now);
                }

                if (inGame)
                {
                    if (!_wasInGame)
                    {
                        _last[0] = null;
                        _last[1] = null;
                        if (!_judgePublishPending[0])
                        {
                            _hookCounts[0] = null;
                        }
                        if (!_judgePublishPending[1])
                        {
                            _hookCounts[1] = null;
                        }
                        _lastResult[0] = null;
                        _lastResult[1] = null;
                        _finalGameplay[0] = null;
                        _finalGameplay[1] = null;
                        _resultHoldUntil = 0;
                        _lastGameplayMetricsCapture = now - GameplayMetricsIntervalMs;
                        _gameplayMetricsReadyAt = now + GameplayMetricsWarmupMs;
                        _lastJudgePublish = now;
                        _server.PublishJson("{\"event\":\"state\",\"status\":\"PLAYING\"}");
                        PublishGameplayStart(now);
                    }

                    CaptureGameplayMetrics(now);
                    PublishPendingJudgements(now, false);
                }
                else if (_wasInGame)
                {
                    PublishPendingJudgements(now, true);
                    for (int player = 0; player < 2; player++)
                    {
                        Snapshot result = RefreshFinalGameplayScore(player, _last[player]);
                        if (result != null)
                        {
                            _server.PublishJson(result.ToJson("settle", "RESULT"));
                            _lastResult[player] = result;
                            _finalGameplay[player] = result;
                            _resultHoldUntil = now + 10000;
                        }
                        _last[player] = null;
                    }
                    _server.PublishJson("{\"event\":\"state\",\"status\":\"IDLE\"}");
                    _presenceRefreshRequested = true;
                }

                if (!inGame && ShouldCapturePresence(now))
                {
                    PresenceSnapshot presence = CapturePresence();
                    if (presence != null)
                    {
                        _server.PublishJson(presence.ToJson());
                    }
                }

                _wasInGame = inGame;
            }
            catch (Exception ex)
            {
                long now = _clock.ElapsedMilliseconds;
                if (now - _lastErrorLog >= 5000)
                {
                    MelonLogger.Warning("XiaoLanMaiBrdge capture error: " + ex.Message);
                    _lastErrorLog = now;
                }
            }
            finally
            {
                LogSlowPath("update", updateStarted, ref _lastSlowUpdateLog);
            }
        }

        public override void OnApplicationQuit()
        {
            StopServer();
        }

        public override void OnDeinitializeMelon()
        {
            StopServer();
        }

        private void StopServer()
        {
            if (ReferenceEquals(_active, this))
            {
                _active = null;
            }
            _advertiseProcess = null;
            _musicSelectProcess = null;
            _entryProcess = null;
            _modeSelectProcess = null;
            _mapSelectProcess = null;
            _ticketSelectProcess = null;
            _characterSelectProcess = null;
            _transitionProcess = null;
            _transitionStatus = null;
            _resultProcess = null;
            _sessionStarted = false;
            SseServer server = _server;
            _server = null;
            if (server != null)
            {
                server.Stop();
            }
            ReleaseInstance();
        }

        private bool TryAcquireInstance()
        {
            try
            {
                bool createdNew;
                _instanceSemaphore = new Semaphore(1, 1, InstanceSemaphoreName, out createdNew);
                _ownsInstanceSemaphore = _instanceSemaphore.WaitOne(0, false);
                if (!_ownsInstanceSemaphore)
                {
                    _instanceSemaphore.Close();
                    _instanceSemaphore = null;
                }
                return _ownsInstanceSemaphore;
            }
            catch (Exception ex)
            {
                MelonLogger.Warning("XiaoLanMaiBrdge single-instance guard unavailable: " + ex.Message);
                return true;
            }
        }

        private void ReleaseInstance()
        {
            Semaphore semaphore = _instanceSemaphore;
            _instanceSemaphore = null;
            if (semaphore == null)
            {
                return;
            }
            if (_ownsInstanceSemaphore)
            {
                _ownsInstanceSemaphore = false;
                try
                {
                    semaphore.Release();
                }
                catch
                {
                }
            }
            semaphore.Close();
        }

        private void PatchJudgeResults()
        {
            HarmonyLib.Harmony harmony = new HarmonyLib.Harmony("XiaoLanMaiBrdge.JudgeResultHook");
            System.Reflection.MethodInfo original = AccessTools.Method(
                typeof(JudgeResultSt),
                "UpdateScore",
                new System.Type[] { typeof(int), typeof(NoteScore.EScoreType), typeof(NoteJudge.ETiming) });
            System.Reflection.MethodInfo postfix = AccessTools.Method(
                typeof(BridgeMod),
                "JudgeResultPostfix");
            if (original == null || postfix == null)
            {
                throw new MissingMethodException("JudgeResultSt.UpdateScore hook target was not found");
            }
            harmony.Patch(original, null, new HarmonyMethod(postfix));
            MelonLogger.Msg("XiaoLanMaiBrdge judge hook installed");
        }

        private void PatchEntryProcess()
        {
            System.Type type = AccessTools.TypeByName("Process.EntryProcess");
            if (type == null)
            {
                MelonLogger.Warning("XiaoLanMaiBrdge entry process type was not found");
                return;
            }

            MethodInfo onStart = AccessTools.Method(type, "OnStart");
            MethodInfo onRelease = AccessTools.Method(type, "OnRelease");
            MethodInfo startPostfix = AccessTools.Method(typeof(BridgeMod), "EntryStartPostfix");
            MethodInfo releasePostfix = AccessTools.Method(typeof(BridgeMod), "EntryReleasePostfix");
            if (onStart == null || onRelease == null || startPostfix == null || releasePostfix == null)
            {
                MelonLogger.Warning("XiaoLanMaiBrdge entry process hooks were not found");
                return;
            }

            HarmonyLib.Harmony harmony = new HarmonyLib.Harmony("XiaoLanMaiBrdge.EntryPresenceHook");
            harmony.Patch(onStart, null, new HarmonyMethod(startPostfix));
            harmony.Patch(onRelease, null, new HarmonyMethod(releasePostfix));
            MelonLogger.Msg("XiaoLanMaiBrdge entry process presence hook installed");
        }

        private static void EntryStartPostfix(object __instance)
        {
            _entryProcess = __instance;
            _sessionStarted = false;
            if (_active != null)
            {
                _active._cachedUserName = string.Empty;
            }
            RequestPresenceRefresh();
        }

        private bool ShouldCapturePresence(long now)
        {
            int interval = _musicSelectProcess == null
                ? Math.Max(_presenceIntervalMs, IdlePresenceIntervalMs)
                : _presenceIntervalMs;
            if (!_presenceRefreshRequested && now - _lastPresencePublish < interval)
            {
                return false;
            }

            _presenceRefreshRequested = false;
            _lastPresencePublish = now;
            return true;
        }

        private bool ShouldCaptureResult(long now)
        {
            if (!_resultRefreshRequested && now - _lastResultPublish < _publishIntervalMs)
            {
                return false;
            }

            _resultRefreshRequested = false;
            _lastResultPublish = now;
            return true;
        }

        private static void RequestPresenceRefresh()
        {
            BridgeMod active = _active;
            if (active != null)
            {
                active._presenceRefreshRequested = true;
            }
        }

        private static void EntryReleasePostfix(object __instance)
        {
            if (ReferenceEquals(_entryProcess, __instance))
            {
                _entryProcess = null;
                ActivateSession();
            }
        }

        private void PatchAdvertiseProcesses()
        {
            PatchAdvertiseProcess("Process.AdvertiseProcess");
            PatchAdvertiseProcess("Process.AdvertiseCommercial.AdvertiseCommercialProcess");
        }

        private static void PatchAdvertiseProcess(string typeName)
        {
            System.Type type = AccessTools.TypeByName(typeName);
            if (type == null)
            {
                return;
            }

            MethodInfo onStart = AccessTools.Method(type, "OnStart");
            MethodInfo onRelease = AccessTools.Method(type, "OnRelease");
            MethodInfo startPostfix = AccessTools.Method(typeof(BridgeMod), "AdvertiseStartPostfix");
            MethodInfo releasePostfix = AccessTools.Method(typeof(BridgeMod), "AdvertiseReleasePostfix");
            if (onStart == null || onRelease == null || startPostfix == null || releasePostfix == null)
            {
                return;
            }

            HarmonyLib.Harmony harmony = new HarmonyLib.Harmony(
                "XiaoLanMaiBrdge.AdvertisePresenceHook." + typeName);
            harmony.Patch(onStart, null, new HarmonyMethod(startPostfix));
            harmony.Patch(onRelease, null, new HarmonyMethod(releasePostfix));
            MelonLogger.Msg("XiaoLanMaiBrdge main menu hook installed: " + typeName);
        }

        private static void AdvertiseStartPostfix(object __instance)
        {
            _advertiseProcess = __instance;
            _entryProcess = null;
            _modeSelectProcess = null;
            _mapSelectProcess = null;
            _ticketSelectProcess = null;
            _characterSelectProcess = null;
            _transitionProcess = null;
            _transitionStatus = null;
            _musicSelectProcess = null;
            _resultProcess = null;
            _sessionStarted = false;
            BridgeMod active = _active;
            if (active != null)
            {
                active._cachedUserName = string.Empty;
                active._selectedMetadata = null;
                active._selectedPresenceMetadata = null;
                active._selectedPresenceRequestedDifficulty = -1;
                active._resultHoldUntil = 0;
                active._lastResult[0] = null;
                active._lastResult[1] = null;
            }
            RequestPresenceRefresh();
        }

        private static void AdvertiseReleasePostfix(object __instance)
        {
            if (ReferenceEquals(_advertiseProcess, __instance))
            {
                _advertiseProcess = null;
                RequestPresenceRefresh();
            }
        }

        private void PatchModeSelectProcess()
        {
            System.Type type = AccessTools.TypeByName("Process.ModeSelect.ModeSelectProcess");
            if (type == null)
            {
                MelonLogger.Warning("XiaoLanMaiBrdge mode select process type was not found");
                return;
            }

            MethodInfo onStart = AccessTools.Method(type, "OnStart");
            MethodInfo onRelease = AccessTools.Method(type, "OnRelease");
            MethodInfo startPostfix = AccessTools.Method(typeof(BridgeMod), "ModeSelectStartPostfix");
            MethodInfo releasePostfix = AccessTools.Method(typeof(BridgeMod), "ModeSelectReleasePostfix");
            if (onStart == null || onRelease == null || startPostfix == null || releasePostfix == null)
            {
                MelonLogger.Warning("XiaoLanMaiBrdge mode select process hooks were not found");
                return;
            }

            HarmonyLib.Harmony harmony = new HarmonyLib.Harmony("XiaoLanMaiBrdge.ModeSelectPresenceHook");
            harmony.Patch(onStart, null, new HarmonyMethod(startPostfix));
            harmony.Patch(onRelease, null, new HarmonyMethod(releasePostfix));
            MelonLogger.Msg("XiaoLanMaiBrdge mode select presence hook installed");
        }

        private static void ModeSelectStartPostfix(object __instance)
        {
            _modeSelectProcess = __instance;
            ActivateSession();
        }

        private static void ModeSelectReleasePostfix(object __instance)
        {
            if (ReferenceEquals(_modeSelectProcess, __instance))
            {
                _modeSelectProcess = null;
                RequestPresenceRefresh();
            }
        }

        private void PatchAuxiliaryPresenceProcesses()
        {
            PatchAuxiliaryPresenceProcess("Process.RegionalSelectProcess");
            PatchAuxiliaryPresenceProcess("Process.TicketSelect.TicketSelectProcess");
            PatchAuxiliaryPresenceProcess("Process.CharacterSelectProces");
            PatchAuxiliaryPresenceProcess("Process.GetPresentProcess");
            PatchAuxiliaryPresenceProcess("Process.PlInformationProcess");
            PatchAuxiliaryPresenceProcess("Process.InformationProcess");
            PatchAuxiliaryPresenceProcess("Process.GetMusicProcess");
            PatchAuxiliaryPresenceProcess("Process.MusicSelectInfoProcess");
        }

        private static void PatchAuxiliaryPresenceProcess(string typeName)
        {
            System.Type type = AccessTools.TypeByName(typeName);
            if (type == null)
            {
                return;
            }

            MethodInfo onStart = AccessTools.Method(type, "OnStart");
            MethodInfo onRelease = AccessTools.Method(type, "OnRelease");
            MethodInfo startPostfix = AccessTools.Method(typeof(BridgeMod), "AuxiliaryStartPostfix");
            MethodInfo releasePostfix = AccessTools.Method(typeof(BridgeMod), "AuxiliaryReleasePostfix");
            if (onStart == null || onRelease == null || startPostfix == null || releasePostfix == null)
            {
                MelonLogger.Warning("XiaoLanMaiBrdge auxiliary process hooks were not found: " + typeName);
                return;
            }

            HarmonyLib.Harmony harmony = new HarmonyLib.Harmony("XiaoLanMaiBrdge.Auxiliary." + typeName);
            harmony.Patch(onStart, null, new HarmonyMethod(startPostfix));
            harmony.Patch(onRelease, null, new HarmonyMethod(releasePostfix));
            MelonLogger.Msg("XiaoLanMaiBrdge auxiliary process hook installed: " + typeName);
        }

        private static void AuxiliaryStartPostfix(object __instance)
        {
            BridgeMod active = _active;
            if (active != null)
            {
                active.SetAuxiliaryProcess(__instance, true);
            }
        }

        private static void AuxiliaryReleasePostfix(object __instance)
        {
            BridgeMod active = _active;
            if (active != null)
            {
                active.SetAuxiliaryProcess(__instance, false);
            }
        }

        private void SetAuxiliaryProcess(object process, bool active)
        {
            if (process == null)
            {
                return;
            }

            _presenceRefreshRequested = true;

            string typeName = process.GetType().FullName ?? string.Empty;
            if (typeName == "Process.RegionalSelectProcess")
            {
                _mapSelectProcess = active ? process :
                    (ReferenceEquals(_mapSelectProcess, process) ? null : _mapSelectProcess);
                if (active)
                {
                    ActivateSession();
                }
                return;
            }
            if (typeName == "Process.TicketSelect.TicketSelectProcess")
            {
                _ticketSelectProcess = active ? process :
                    (ReferenceEquals(_ticketSelectProcess, process) ? null : _ticketSelectProcess);
                if (active)
                {
                    ActivateSession();
                }
                return;
            }
            if (typeName == "Process.CharacterSelectProces")
            {
                _characterSelectProcess = active ? process :
                    (ReferenceEquals(_characterSelectProcess, process) ? null : _characterSelectProcess);
                if (active)
                {
                    ActivateSession();
                }
                return;
            }

            string status = AuxiliaryStatus(typeName);
            if (string.IsNullOrEmpty(status))
            {
                return;
            }
            if (active)
            {
                _transitionProcess = process;
                _transitionStatus = status;
            }
            else if (ReferenceEquals(_transitionProcess, process))
            {
                _transitionProcess = null;
                _transitionStatus = null;
            }
        }

        private static string AuxiliaryStatus(string typeName)
        {
            switch (typeName)
            {
                case "Process.GetPresentProcess":
                    return "PRESENTS";
                case "Process.PlInformationProcess":
                case "Process.InformationProcess":
                    return "GAME_INFO";
                case "Process.GetMusicProcess":
                case "Process.MusicSelectInfoProcess":
                    return "LOADING";
                default:
                    return string.Empty;
            }
        }

        private void PatchMusicSelect()
        {
            System.Type type = AccessTools.TypeByName("Process.MusicSelectProcess");
            if (type == null)
            {
                MelonLogger.Warning("XiaoLanMaiBrdge music select type was not found; menu presence only");
                return;
            }

            MethodInfo onStart = AccessTools.Method(type, "OnStart");
            MethodInfo onRelease = AccessTools.Method(type, "OnRelease");
            MethodInfo startPostfix = AccessTools.Method(typeof(BridgeMod), "MusicSelectStartPostfix");
            MethodInfo releasePostfix = AccessTools.Method(typeof(BridgeMod), "MusicSelectReleasePostfix");
            if (onStart == null || onRelease == null || startPostfix == null || releasePostfix == null)
            {
                MelonLogger.Warning("XiaoLanMaiBrdge music select hooks were not found; menu presence only");
                return;
            }

            HarmonyLib.Harmony harmony = new HarmonyLib.Harmony("XiaoLanMaiBrdge.MusicSelectPresenceHook");
            harmony.Patch(onStart, null, new HarmonyMethod(startPostfix));
            harmony.Patch(onRelease, null, new HarmonyMethod(releasePostfix));
            MelonLogger.Msg("XiaoLanMaiBrdge music select presence hook installed");
        }

        private static void MusicSelectStartPostfix(object __instance)
        {
            _musicSelectProcess = __instance;
            BridgeMod active = _active;
            if (active != null)
            {
                active._selectedPresenceMetadata = null;
                active._selectedPresenceRequestedDifficulty = -1;
            }
            ActivateSession();
        }

        private static void MusicSelectReleasePostfix(object __instance)
        {
            if (ReferenceEquals(_musicSelectProcess, __instance))
            {
                _musicSelectProcess = null;
                RequestPresenceRefresh();
            }
        }

        private void PatchResultProcess()
        {
            System.Type type = AccessTools.TypeByName("Process.ResultProcess");
            if (type == null)
            {
                MelonLogger.Warning("XiaoLanMaiBrdge result process type was not found");
                return;
            }

            MethodInfo onStart = AccessTools.Method(type, "OnStart");
            MethodInfo onRelease = AccessTools.Method(type, "OnRelease");
            MethodInfo startPostfix = AccessTools.Method(typeof(BridgeMod), "ResultStartPostfix");
            MethodInfo releasePostfix = AccessTools.Method(typeof(BridgeMod), "ResultReleasePostfix");
            if (onStart == null || onRelease == null || startPostfix == null || releasePostfix == null)
            {
                MelonLogger.Warning("XiaoLanMaiBrdge result process hooks were not found");
                return;
            }

            HarmonyLib.Harmony harmony = new HarmonyLib.Harmony("XiaoLanMaiBrdge.ResultPresenceHook");
            harmony.Patch(onStart, null, new HarmonyMethod(startPostfix));
            harmony.Patch(onRelease, null, new HarmonyMethod(releasePostfix));
            MelonLogger.Msg("XiaoLanMaiBrdge result presence hook installed");
        }

        private static void ResultStartPostfix(object __instance)
        {
            _resultProcess = __instance;
            ActivateSession();
            BridgeMod active = _active;
            if (active != null)
            {
                active._lastResult[0] = null;
                active._lastResult[1] = null;
                active._resultHoldUntil = 0;
                active._resultRefreshRequested = true;
            }
        }

        private static void ResultReleasePostfix(object __instance)
        {
            if (ReferenceEquals(_resultProcess, __instance))
            {
                _resultProcess = null;
                RequestPresenceRefresh();
                BridgeMod active = _active;
                if (active != null)
                {
                    active._resultRefreshRequested = false;
                    if (active._lastResult[0] != null || active._lastResult[1] != null)
                    {
                        active._resultHoldUntil = active._clock.ElapsedMilliseconds + 10000;
                    }
                }
            }
        }

        private void CaptureResultEvents(long now)
        {
            if (_resultProcess == null)
            {
                return;
            }

            for (int player = 0; player < 2; player++)
            {
                Snapshot result = CaptureResult(_resultProcess, player);
                if (result == null)
                {
                    continue;
                }

                bool changed = _lastResult[player] == null || !_lastResult[player].SameValues(result);
                if (changed)
                {
                    _server.PublishJson(result.ToJson("settle", "RESULT"));
                    _lastResult[player] = result;
                    _resultHoldUntil = now + 10000;
                }
            }
        }

        private Snapshot CaptureResult(object resultProcess, int player)
        {
            try
            {
                object scoreLists = ReadFirstMember(
                    resultProcess, "_gameScoreLists", "gameScoreLists", "GameScoreLists");
                object score = ReadIndex(scoreLists, player);
                object userScore = ReadIndex(
                    ReadFirstMember(resultProcess, "_userScores", "userScores"), player);
                if (score == null && userScore == null)
                {
                    score = GamePlayManager.Instance.GetGameScore(player, -1);
                }
                if (score == null && userScore == null)
                {
                    return null;
                }
                object scoreEnabled = ReadFirstMember(score, "IsEnable", "isEnable");
                if (scoreEnabled != null && !ToBool(scoreEnabled))
                {
                    return null;
                }

                object sessionInfo = ReadFirstMember(score, "SessionInfo", "sessionInfo");
                int musicId = ToInt(ReadFirstMember(
                    resultProcess, "_musicID", "musicID", "MusicID", "musicId"));
                int sessionMusicId = ToInt(ReadFirstMember(sessionInfo, "musicId", "MusicId"));
                if (musicId <= 0 && sessionMusicId > 0)
                {
                    musicId = sessionMusicId;
                }
                Snapshot previous = _last[player];
                Snapshot baseline = _finalGameplay[player] ?? _lastResult[player] ?? previous;
                if (musicId <= 0 && baseline != null)
                {
                    musicId = baseline.MusicId;
                }

                bool matchingBaseline = baseline != null &&
                                        baseline.MusicId > 0 &&
                                        baseline.MusicId == musicId;
                int difficulty = matchingBaseline ? baseline.Difficulty : -1;
                if (difficulty < 0 || difficulty > 5)
                {
                    object sessionDifficulty = ReadFirstMember(
                        sessionInfo, "difficulty", "Difficulty");
                    int value = ToInt(sessionDifficulty);
                    difficulty = sessionDifficulty != null && value >= 0 && value < 6
                        ? value
                        : ReadResultDifficulty(player);
                }

                uint track = matchingBaseline ? baseline.Track : GameManager.MusicTrackNumber;
                Snapshot snapshot = new Snapshot
                {
                    Player = player + 1,
                    Track = track,
                    MusicId = musicId,
                    Difficulty = difficulty
                };
                if (matchingBaseline)
                {
                    CopyScoreValues(baseline, snapshot);
                }
                ApplyFinalScoreValues(snapshot, score, userScore);
                Snapshot metadataSource = matchingBaseline ? baseline : null;
                if (metadataSource != null &&
                    metadataSource.MusicId == snapshot.MusicId &&
                    metadataSource.Difficulty == snapshot.Difficulty &&
                    !string.IsNullOrEmpty(metadataSource.Title))
                {
                    CopyMetadata(metadataSource, snapshot);
                }
                else
                {
                    ApplyResultMetadata(snapshot, musicId, difficulty);
                }
                if (previous != null && previous.MusicId == snapshot.MusicId)
                {
                    if (snapshot.MusicId <= 0 || string.IsNullOrEmpty(snapshot.Title))
                    {
                        CopyMetadata(previous, snapshot);
                    }
                    if (snapshot.Track == 0)
                    {
                        snapshot.Track = previous.Track;
                    }
                }
                ApplyIdentity(snapshot);
                return snapshot;
            }
            catch (Exception ex)
            {
                if (!_metadataWarningLogged)
                {
                    _metadataWarningLogged = true;
                    MelonLogger.Warning("XiaoLanMaiBrdge result capture unavailable: " + ex.Message);
                }
                return null;
            }
        }

        private static int ReadResultDifficulty(int player)
        {
            object values = ReadStaticMember(typeof(GameManager), "SelectDifficultyID");
            object value = ReadIndex(values, player);
            if (value == null)
            {
                value = ReadStaticMember(typeof(GameManager), "CurrentDifficulty");
                value = ReadIndex(value, player);
            }
            int difficulty = ToInt(value);
            return value != null && difficulty >= 0 && difficulty < 6 ? difficulty : -1;
        }

        private void ApplyResultMetadata(Snapshot snapshot, int musicId, int difficulty)
        {
            if (musicId <= 0 || difficulty < 0)
            {
                return;
            }

            System.Type dataManagerType = AccessTools.TypeByName("Manager.DataManager");
            object dataManager = ReadStaticMember(dataManagerType, "Instance");
            if (dataManager == null)
            {
                return;
            }
            MethodInfo getMusic = FindMethod(dataManager.GetType(), "GetMusic", false, typeof(int));
            object music = getMusic == null ? null : getMusic.Invoke(dataManager, new object[] { musicId });
            if (music == null)
            {
                return;
            }

            bool isUtage = IsUtageMusic(music, musicId);
            int notesDifficulty = isUtage ? 0 : ResolveExistingDifficulty(null, music, difficulty);
            snapshot.MusicId = musicId;
            snapshot.Difficulty = isUtage ? 5 : notesDifficulty;
            snapshot.Chart = isUtage ? UtageChartName(music) : DifficultyName(notesDifficulty);
            snapshot.Title = ReadStringId(music, "name");
            snapshot.Composer = ReadStringId(music, "artistName");
            snapshot.Artist = snapshot.Composer;

            object notes = ReadNotesForDifficulty(null, music, notesDifficulty);
            if (notes == null)
            {
                return;
            }
            int musicLevelId = ToInt(ReadMember(notes, "musicLevelID"));
            MethodInfo getMusicLevel = FindMethod(dataManager.GetType(), "GetMusicLevel", false, typeof(int));
            object musicLevel = getMusicLevel == null
                ? null
                : getMusicLevel.Invoke(dataManager, new object[] { musicLevelId });
            snapshot.Constant = ToDecimal(ReadMember(notes, "level")) +
                                ToDecimal(ReadMember(notes, "levelDecimal")) / 10m;
            snapshot.Author = ReadStringId(notes, "notesDesigner");
            snapshot.Level = ToText(ReadMember(musicLevel, "levelNum"));
            if (string.IsNullOrEmpty(snapshot.Level) && snapshot.Constant > 0m)
            {
                snapshot.Level = snapshot.Constant.ToString("0.#", CultureInfo.InvariantCulture);
            }
        }

        private PresenceSnapshot CapturePresence()
        {
            PresenceSnapshot presence = new PresenceSnapshot();
            if (string.IsNullOrEmpty(_cachedVersion))
            {
                _cachedVersion = ReadVersion();
            }
            presence.Version = _cachedVersion;
            if (_sessionStarted)
            {
                long now = _clock.ElapsedMilliseconds;
                if (IsGuestName(_cachedUserName) &&
                    now - _lastUserNameRead >= UserNameRetryIntervalMs)
                {
                    _lastUserNameRead = now;
                    string userName = ReadUserName();
                    if (!IsGuestName(userName))
                    {
                        _cachedUserName = userName;
                    }
                }
                presence.UserName = _cachedUserName;
            }
            if (_entryProcess != null)
            {
                presence.Status = "LOGIN";
                ReadProcessTimer(_entryProcess, out presence.Remaining, out presence.TimerInfinite);
                return presence;
            }
            if (_advertiseProcess != null)
            {
                presence.Status = "MENU";
                presence.UserName = string.Empty;
                return presence;
            }
            if (_modeSelectProcess != null)
            {
                presence.Status = "MODE_SELECT";
                ReadProcessTimer(_modeSelectProcess, out presence.Remaining, out presence.TimerInfinite);
                return presence;
            }
            if (_mapSelectProcess != null)
            {
                presence.Status = "MAP_SELECT";
                ReadProcessTimer(_mapSelectProcess, out presence.Remaining, out presence.TimerInfinite);
                return presence;
            }
            if (_ticketSelectProcess != null)
            {
                presence.Status = "TICKET_SELECT";
                ReadProcessTimer(_ticketSelectProcess, out presence.Remaining, out presence.TimerInfinite);
                return presence;
            }
            if (_characterSelectProcess != null)
            {
                presence.Status = "CHARACTER_SELECT";
                ReadProcessTimer(_characterSelectProcess, out presence.Remaining, out presence.TimerInfinite);
                return presence;
            }
            if (_transitionProcess != null)
            {
                presence.Status = string.IsNullOrEmpty(_transitionStatus) ? "LOADING" : _transitionStatus;
                ReadProcessTimer(_transitionProcess, out presence.Remaining, out presence.TimerInfinite);
                return presence;
            }
            if (_resultProcess != null)
            {
                presence.Status = "RESULT_SCREEN";
                return presence;
            }
            if (_resultHoldUntil > _clock.ElapsedMilliseconds)
            {
                presence.Status = "RESULT_SCREEN";
                return presence;
            }
            object process = _musicSelectProcess;
            if (process == null)
            {
                presence.Status = _sessionStarted ? "LOADING" : "MENU";
                return presence;
            }

            presence.Status = "SELECTING";
            object selected = InvokeMethod(process, "GetMusic", 0);
            object currentSelection = ReadFirstMember(
                process, "CurrentMusicSelect", "_currentMusicSelect", "CurrentMusic", "_currentMusic");
            if (selected == null)
            {
                selected = currentSelection;
            }
            object musicSelectData = ReadFirstMember(
                selected, "musicSelectData", "MusicSelectData", "data", "Data");
            if (musicSelectData == null)
            {
                musicSelectData = ReadFirstMember(
                    currentSelection, "musicSelectData", "MusicSelectData", "data", "Data");
            }
            if (musicSelectData == null)
            {
                musicSelectData = selected ?? currentSelection;
            }
            presence.DifficultyId = PopulateSelectedDifficulty(process, musicSelectData, presence);
            int requestedDifficulty = presence.DifficultyId;
            presence.Difficulty = DifficultyName(presence.DifficultyId);
            object music = ReadMember(musicSelectData, "MusicData");
            if (music == null)
            {
                music = musicSelectData;
            }
            presence.MusicId = ToInt(ReadMember(music, "id"));
            if (presence.MusicId <= 0)
            {
                presence.MusicId = ToInt(ReadMember(ReadMember(music, "name"), "id"));
            }

            if (TryApplySelectedPresenceMetadata(presence, requestedDifficulty))
            {
                ReadProcessTimer(process, out presence.Remaining, out presence.TimerInfinite);
                CacheSelectedMetadata(presence);
                return presence;
            }

            presence.Title = ReadStringId(music, "name");
            presence.Composer = ReadStringId(music, "artistName");
            presence.Artist = presence.Composer;

            bool isUtage = IsUtageMusic(music, presence.MusicId);
            int notesDifficulty = presence.DifficultyId;
            if (isUtage)
            {
                notesDifficulty = 0;
                presence.DifficultyId = 5;
                presence.Difficulty = UtageChartName(music);
            }
            else
            {
                notesDifficulty = ResolveExistingDifficulty(
                    musicSelectData, music, presence.DifficultyId);
                presence.DifficultyId = notesDifficulty;
                presence.Difficulty = DifficultyName(notesDifficulty);
            }

            object notes = ReadNotesForDifficulty(musicSelectData, music, notesDifficulty);
            if (notes != null)
            {
                presence.Author = ReadStringId(notes, "notesDesigner");
                int musicLevelId = ToInt(ReadMember(notes, "musicLevelID"));
                System.Type dataManagerType = AccessTools.TypeByName("Manager.DataManager");
                object dataManager = ReadStaticMember(dataManagerType, "Instance");
                MethodInfo getMusicLevel = dataManager == null
                    ? null
                    : FindMethod(dataManager.GetType(), "GetMusicLevel", false, typeof(int));
                object musicLevel = getMusicLevel == null
                    ? null
                    : getMusicLevel.Invoke(dataManager, new object[] { musicLevelId });
                presence.Constant = ToDecimal(ReadMember(notes, "level")) +
                                    ToDecimal(ReadMember(notes, "levelDecimal")) / 10m;
                presence.Level = ToText(ReadMember(musicLevel, "levelNum"));
                if (string.IsNullOrEmpty(presence.Level) && presence.Constant > 0m)
                {
                    presence.Level = presence.Constant.ToString("0.#", CultureInfo.InvariantCulture);
                }
            }

            ReadProcessTimer(process, out presence.Remaining, out presence.TimerInfinite);
            StoreSelectedPresenceMetadata(presence, requestedDifficulty);
            CacheSelectedMetadata(presence);
            return presence;
        }

        private bool TryApplySelectedPresenceMetadata(PresenceSnapshot presence, int requestedDifficulty)
        {
            PresenceSnapshot cached = _selectedPresenceMetadata;
            if (cached == null || presence.MusicId <= 0 || cached.MusicId != presence.MusicId ||
                _selectedPresenceRequestedDifficulty != requestedDifficulty)
            {
                return false;
            }

            presence.MusicId = cached.MusicId;
            presence.DifficultyId = cached.DifficultyId;
            presence.Difficulty = cached.Difficulty;
            presence.Title = cached.Title;
            presence.Artist = cached.Artist;
            presence.Author = cached.Author;
            presence.Composer = cached.Composer;
            presence.Level = cached.Level;
            presence.Constant = cached.Constant;
            return true;
        }

        private void StoreSelectedPresenceMetadata(PresenceSnapshot presence, int requestedDifficulty)
        {
            if (presence == null || presence.MusicId <= 0)
            {
                return;
            }

            _selectedPresenceMetadata = new PresenceSnapshot
            {
                MusicId = presence.MusicId,
                DifficultyId = presence.DifficultyId,
                Difficulty = presence.Difficulty,
                Title = presence.Title,
                Artist = presence.Artist,
                Author = presence.Author,
                Composer = presence.Composer,
                Level = presence.Level,
                Constant = presence.Constant
            };
            _selectedPresenceRequestedDifficulty = requestedDifficulty;
        }

        private void CacheSelectedMetadata(PresenceSnapshot presence)
        {
            if (presence == null || presence.MusicId <= 0)
            {
                return;
            }

            Snapshot metadata = _selectedMetadata ?? new Snapshot();
            metadata.MusicId = presence.MusicId;
            metadata.Difficulty = presence.DifficultyId;
            metadata.Title = presence.Title;
            metadata.Artist = presence.Artist;
            metadata.Author = presence.Author;
            metadata.Composer = presence.Composer;
            metadata.Chart = presence.Difficulty;
            metadata.Level = presence.Level;
            metadata.Constant = presence.Constant;
            _selectedMetadata = metadata;
        }

        private static int ReadSelectedDifficulty(object process, object selected)
        {
            return PopulateSelectedDifficulty(process, selected, new PresenceSnapshot());
        }

        private static int PopulateSelectedDifficulty(
            object process, object selected, PresenceSnapshot presence)
        {
            object gameDifficulty = InvokeMethod(process, "GetDifficulty", 0, 0);
            int gameDifficultyValue = ReadDifficultyValue(gameDifficulty);
            presence.GameDifficultyId = gameDifficultyValue;
            presence.CurrentDifficultyId = ReadDifficultyValue(
                InvokeMethod(process, "GetCurrentDifficulty", 0));
            presence.SelectDifficultyIndex = ReadDifficultyValue(
                InvokeMethod(process, "GetDifficultySelectIndex", 0));
            presence.CardDifficultyId = ReadDifficultyValue(ReadFirstMember(
                selected, "Difficulty", "difficulty", "DifficultyId", "difficultyId", "SelectDifficultyID"));
            presence.IsLevelTab = ToBool(InvokeMethod(process, "IsLevelTab", 0));
            presence.IsExtraFolder = ToBool(InvokeMethod(process, "IsExtraFolder", 0));
            if (gameDifficultyValue >= 0)
            {
                return gameDifficultyValue;
            }

            if (!presence.IsLevelTab && !presence.IsExtraFolder)
            {
                if (presence.CurrentDifficultyId >= 0)
                {
                    return presence.CurrentDifficultyId;
                }
            }

            if (presence.SelectDifficultyIndex >= 0)
            {
                return presence.SelectDifficultyIndex;
            }

            if (presence.CardDifficultyId >= 0)
            {
                return presence.CardDifficultyId;
            }

            if (presence.CurrentDifficultyId >= 0)
            {
                return presence.CurrentDifficultyId;
            }

            object current = ReadFirstMember(
                process, "CurrentDifficulty", "_currentDifficulty", "SelectDifficultyID", "_selectDifficultyID");
            object currentValue = ReadIndex(current, 0);
            if (currentValue == null)
            {
                currentValue = current;
            }
            int currentDifficulty = ToInt(currentValue);
            return currentValue != null && currentDifficulty >= 0 && currentDifficulty < 6
                ? currentDifficulty
                : -1;
        }

        private static int ReadDifficultyValue(object value)
        {
            int difficulty = ToInt(value);
            return value != null && difficulty >= 0 && difficulty < 6 ? difficulty : -1;
        }

        private static void ReadProcessTimer(object process, out int remaining, out bool infinite)
        {
            remaining = 0;
            infinite = false;
            object genericTimer = ReadGenericTimer(process);
            object genericRemaining = ReadFirstMember(
                genericTimer, "CountDownSecond", "Remaining", "CountDown", "Seconds");
            object genericInfinite = ReadFirstMember(
                genericTimer, "IsInfinity", "IsInfinite", "TimerInfinite");
            bool hasRemaining = genericRemaining != null;
            bool hasInfinite = genericInfinite != null;
            if (hasRemaining)
            {
                remaining = ToInt(genericRemaining);
            }
            if (hasInfinite)
            {
                infinite = ToBool(genericInfinite);
            }
            if (hasRemaining && hasInfinite)
            {
                return;
            }

            object current = process;
            for (int depth = 0; current != null && depth < 5; depth++)
            {
                if (!hasRemaining)
                {
                    object direct = ReadFirstMember(
                        current, "CountDownSecond", "Remaining", "CountDown", "Seconds");
                    if (direct != null)
                    {
                        remaining = ToInt(direct);
                        hasRemaining = true;
                    }
                }
                if (!hasInfinite)
                {
                    object value = ReadFirstMember(
                        current, "IsInfinity", "IsInfinite", "TimerInfinite");
                    if (value != null)
                    {
                        infinite = ToBool(value);
                        hasInfinite = true;
                    }
                }
                if (hasRemaining && hasInfinite)
                {
                    return;
                }

                object timer = ReadFirstMember(current, "_timer", "Timer", "_monitor_timer", "MonitorTimer");
                if (timer == null)
                {
                    timer = ReadIndex(ReadFirstMember(current, "Monitors", "_monitors"), 0);
                }
                if (timer == null)
                {
                    object context = ReadFirstMember(current, "Context", "_context");
                    object state = context == null ? null : InvokeNoArg(context, "GetCurrentState");
                    if (state != null && !ReferenceEquals(state, current))
                    {
                        current = state;
                        continue;
                    }
                    break;
                }
                current = ReadIndex(timer, 0) ?? timer;
            }
        }

        private static int ReadProcessRemaining(object process)
        {
            int remaining;
            bool infinite;
            ReadProcessTimer(process, out remaining, out infinite);
            return remaining;
        }

        private static bool ReadProcessTimerInfinite(object process)
        {
            int remaining;
            bool infinite;
            ReadProcessTimer(process, out remaining, out infinite);
            return infinite;
        }

        private static object ReadGenericTimer(object process)
        {
            object processManager = ReadMember(ReadMember(process, "container"), "processManager");
            object genericManager = ReadMember(processManager, "_genericManager");
            object timerController = ReadMember(genericManager, "_timerController");
            return ReadIndex(timerController, 0);
        }

        private static object InvokeNoArg(object target, string name)
        {
            if (target == null)
            {
                return null;
            }
            MethodInfo method = FindMethod(target.GetType(), name, false);
            return method == null ? null : method.Invoke(target, null);
        }

        private static object ReadFirstMember(object target, params string[] names)
        {
            if (target == null || names == null)
            {
                return null;
            }
            foreach (string name in names)
            {
                object value = ReadMember(target, name);
                if (value != null)
                {
                    return value;
                }
            }
            return null;
        }

        private static object ReadFirstMember(object target, string name0, string name1)
        {
            object value = ReadMember(target, name0);
            return value ?? ReadMember(target, name1);
        }

        private static object ReadFirstMember(
            object target, string name0, string name1, string name2)
        {
            object value = ReadMember(target, name0) ?? ReadMember(target, name1);
            return value ?? ReadMember(target, name2);
        }

        private static object ReadFirstMember(
            object target, string name0, string name1, string name2, string name3)
        {
            object value = ReadMember(target, name0) ?? ReadMember(target, name1);
            value = value ?? ReadMember(target, name2);
            return value ?? ReadMember(target, name3);
        }

        private static object ReadFirstMember(
            object target, string name0, string name1, string name2, string name3, string name4)
        {
            object value = ReadMember(target, name0) ?? ReadMember(target, name1);
            value = value ?? ReadMember(target, name2);
            value = value ?? ReadMember(target, name3);
            return value ?? ReadMember(target, name4);
        }

        private static object InvokeMethod(object target, string name, params object[] arguments)
        {
            if (target == null)
            {
                return null;
            }
            if (arguments != null && arguments.Length == 2)
            {
                MethodInfo pairMethod = FindMethod(
                    target.GetType(), name, false, typeof(int), typeof(int));
                return pairMethod == null ? null : pairMethod.Invoke(target, arguments);
            }
            MethodInfo method = FindMethod(target.GetType(), name, false, typeof(int));
            if (method != null)
            {
                return method.Invoke(target, arguments);
            }
            method = FindMethod(target.GetType(), name, false, typeof(long));
            if (method == null || arguments == null || arguments.Length != 1)
            {
                return null;
            }
            return method.Invoke(
                target,
                new object[] { Convert.ToInt64(arguments[0], CultureInfo.InvariantCulture) });
        }

        private static object ReadIndex(object target, int index)
        {
            if (target == null)
            {
                return null;
            }
            System.Collections.IList list = target as System.Collections.IList;
            if (list != null && index >= 0 && index < list.Count)
            {
                return list[index];
            }
            Array array = target as Array;
            if (array != null && index >= 0 && index < array.Length)
            {
                return array.GetValue(index);
            }
            PropertyInfo item;
            System.Type type = target.GetType();
            lock (MemberCacheLock)
            {
                if (!IntegerIndexerCache.TryGetValue(type, out item))
                {
                    item = type.GetProperty("Item", new System.Type[] { typeof(int) });
                    IntegerIndexerCache[type] = item;
                }
            }
            try
            {
                return item == null ? null : item.GetValue(target, new object[] { index });
            }
            catch
            {
                return null;
            }
        }

        private static bool ToBool(object value)
        {
            try
            {
                return value != null && Convert.ToBoolean(value, CultureInfo.InvariantCulture);
            }
            catch
            {
                return false;
            }
        }

        private static string ReadUserName()
        {
            try
            {
                System.Type userManagerType = AccessTools.TypeByName("Manager.UserDataManager");
                object userManager = ReadStaticMember(userManagerType, "Instance");
                if (userManager != null)
                {
                    for (int index = 0; index < 2; index++)
                    {
                        object user = InvokeMethod(userManager, "GetUserData", index);
                        string name = ReadUserNameFromData(user);
                        if (!IsGuestName(name))
                        {
                            return name;
                        }
                    }
                }

                System.Type netManagerType = AccessTools.TypeByName("Manager.NetDataManager");
                object netManager = ReadStaticMember(netManagerType, "Instance");
                if (netManager != null)
                {
                    for (int index = 0; index < 2; index++)
                    {
                        object user = InvokeMethod(netManager, "GetNetUserData", index);
                        string name = ReadUserNameFromData(user);
                        if (!IsGuestName(name))
                        {
                            return name;
                        }
                    }
                }
            }
            catch
            {
                // User data is not available during boot and logout transitions.
            }
            return string.Empty;
        }

        private static bool HasEnteredUser()
        {
            try
            {
                System.Type userManagerType = AccessTools.TypeByName("Manager.UserDataManager");
                object userManager = ReadStaticMember(userManagerType, "Instance");
                if (userManager == null)
                {
                    return false;
                }
                for (int index = 0; index < 2; index++)
                {
                    object user = InvokeMethod(userManager, "GetUserData", index);
                    if (ToBool(ReadMember(user, "IsEntry")))
                    {
                        return true;
                    }
                }
            }
            catch
            {
                return false;
            }
            return false;
        }

        private static void ActivateSession()
        {
            _sessionStarted = true;
            BridgeMod active = _active;
            if (active == null)
            {
                return;
            }
            string userName = ReadUserName();
            if (!IsGuestName(userName))
            {
                active._cachedUserName = userName;
            }
            active._lastUserNameRead = active._clock.ElapsedMilliseconds;
            active._presenceRefreshRequested = true;
        }

        private static string ReadUserNameFromData(object user)
        {
            if (user == null)
            {
                return string.Empty;
            }
            object detail = ReadFirstMember(user, "Detail", "detail");
            string name = ToText(ReadFirstMember(detail, "userName", "UserName"));
            if (string.IsNullOrEmpty(name))
            {
                name = ToText(ReadFirstMember(user, "userName", "UserName"));
            }
            return name;
        }

        private static bool IsGuestName(string name)
        {
            if (string.IsNullOrEmpty(name))
            {
                return true;
            }
            string normalized = name.Normalize(NormalizationForm.FormKC).Trim();
            return string.Equals(normalized, "\u6e38\u5ba2", StringComparison.Ordinal) ||
                   string.Equals(normalized, "GUEST", StringComparison.OrdinalIgnoreCase) ||
                   string.Equals(normalized, "\u30b2\u30b9\u30c8", StringComparison.Ordinal);
        }

        private static string ReadVersion()
        {
            try
            {
                System.Type configType = AccessTools.TypeByName("MAI2System.SystemConfig");
                object systemConfig = ReadStaticMember(configType, "Instance");
                object config = ReadMember(systemConfig, "config");
                if (config == null)
                {
                    config = ReadStaticMember(configType, "config");
                }
                string display = ToText(ReadMember(config, "displayVersionString"));
                if (string.IsNullOrEmpty(display))
                {
                    display = ToText(ReadMember(config, "_displayVersionString"));
                }
                if (!string.IsNullOrEmpty(display))
                {
                    return display;
                }
                object rom = ReadMember(config, "romVersionInfo") ??
                             ReadMember(config, "_romVersionInfo");
                object versionNo = ReadMember(rom, "versionNo") ??
                                   ReadMember(rom, "_versionNo");
                string version = ToText(ReadMember(versionNo, "versionString"));
                if (string.IsNullOrEmpty(version))
                {
                    version = ToText(ReadMember(versionNo, "_versionString"));
                }
                if (!string.IsNullOrEmpty(version))
                {
                    return version;
                }

                System.Type amManagerType = AccessTools.TypeByName("Manager.AmManager");
                object amManager = ReadStaticMember(amManagerType, "Instance");
                versionNo = ReadMember(amManager, "VersionNo");
                return ToText(ReadMember(versionNo, "versionString"));
            }
            catch
            {
                return string.Empty;
            }
        }

        private void PublishGameplayStart(long now)
        {
            uint track = GameManager.MusicTrackNumber;
            for (int player = 0; player < 2; player++)
            {
                Snapshot counts = _hookCounts[player];
                if (counts == null || counts.Track != track)
                {
                    counts = new Snapshot { Player = player + 1, Track = track };
                    if (_selectedMetadata != null)
                    {
                        CopyMetadata(_selectedMetadata, counts);
                    }
                    ApplyIdentity(counts);
                    _hookCounts[player] = counts;
                }
                _last[player] = counts;
                _server.PublishJson(counts.ToJson("counts", "PLAYING"));
                _judgePublishPending[player] = false;
            }
            _lastJudgePublish = now;
        }

        private void PublishPendingJudgements(long now, bool force)
        {
            if (!force && now - _lastJudgePublish < _publishIntervalMs)
            {
                return;
            }

            bool published = false;
            for (int player = 0; player < 2; player++)
            {
                if (!_judgePublishPending[player])
                {
                    continue;
                }

                Snapshot counts = _hookCounts[player];
                if (counts != null)
                {
                    _server.PublishJson(counts.ToJson("counts", "PLAYING"));
                    published = true;
                }
                _judgePublishPending[player] = false;
            }
            if (published)
            {
                _lastJudgePublish = now;
            }
        }

        private void CaptureGameplayMetrics(long now)
        {
            if (now < _gameplayMetricsReadyAt ||
                now - _lastGameplayMetricsCapture < GameplayMetricsIntervalMs)
            {
                return;
            }

            long metricsStarted = Stopwatch.GetTimestamp();
            bool sampled = false;
            uint track = GameManager.MusicTrackNumber;
            for (int player = 0; player < 2; player++)
            {
                Snapshot counts = _hookCounts[player];
                if (counts == null || counts.Track != track || counts.TotalJudgements == 0)
                {
                    continue;
                }

                sampled = true;
                try
                {
                    GameScoreList score = GamePlayManager.Instance.GetGameScore(player, -1);
                    if (score == null || !score.IsEnable)
                    {
                        continue;
                    }

                    counts.DxScore = score.DxScore;
                    counts.Achievement = score.GetAchivement();
                    decimal progress;
                    uint elapsedSeconds;
                    uint durationSeconds;
                    if (TryReadGameplayTime(
                        player, out progress, out elapsedSeconds, out durationSeconds))
                    {
                        counts.Progress = progress;
                        counts.ElapsedSeconds = elapsedSeconds;
                        counts.DurationSeconds = durationSeconds;
                    }
                    _last[player] = counts;
                    _judgePublishPending[player] = true;
                }
                catch (Exception ex)
                {
                    if (!_gameplayMetricsWarningLogged)
                    {
                        _gameplayMetricsWarningLogged = true;
                        MelonLogger.Warning("XiaoLanMaiBrdge gameplay metrics unavailable: " + ex.Message);
                    }
                }
            }

            if (sampled)
            {
                _lastGameplayMetricsCapture = now;
            }
            LogSlowPath("gameplay metrics", metricsStarted, ref _lastSlowMetricsLog);
        }

        private Snapshot RefreshFinalGameplayScore(int player, Snapshot snapshot)
        {
            if (snapshot == null)
            {
                return null;
            }
            try
            {
                object score = GamePlayManager.Instance.GetGameScore(player, -1);
                object scoreEnabled = ReadFirstMember(score, "IsEnable", "isEnable");
                if (scoreEnabled != null && !ToBool(scoreEnabled))
                {
                    return null;
                }
                ApplyFinalScoreValues(snapshot, score, null);
            }
            catch (Exception ex)
            {
                if (!_gameplayMetricsWarningLogged)
                {
                    _gameplayMetricsWarningLogged = true;
                    MelonLogger.Warning("XiaoLanMaiBrdge final score unavailable: " + ex.Message);
                }
            }
            return snapshot;
        }

        private static void ApplyFinalScoreValues(Snapshot snapshot, object score, object userScore)
        {
            if (snapshot == null)
            {
                return;
            }
            if (score == null && userScore == null)
            {
                return;
            }

            uint critical = ToUInt(ReadFirstMember(score, "CriticalNum", "criticalNum"));
            uint perfect = ToUInt(ReadFirstMember(score, "PerfectNum", "perfectNum"));
            uint great = ToUInt(ReadFirstMember(score, "GreatNum", "greatNum"));
            uint good = ToUInt(ReadFirstMember(score, "GoodNum", "goodNum"));
            uint miss = ToUInt(ReadFirstMember(score, "MissNum", "missNum"));
            if (critical + perfect + great + good + miss > 0)
            {
                snapshot.Critical = critical;
                snapshot.Perfect = perfect;
                snapshot.Great = great;
                snapshot.Good = good;
                snapshot.Miss = miss;
            }

            object comboValue = ReadFirstMember(score, "MaxCombo", "maxCombo");
            if (comboValue == null)
            {
                comboValue = ReadFirstMember(score, "Combo", "combo");
            }
            if (comboValue != null)
            {
                uint combo = ToUInt(comboValue);
                if (combo > 0 || snapshot.Combo == 0)
                {
                    snapshot.Combo = combo;
                }
            }

            object dxScoreValue = ReadFirstMember(score, "DxScore", "dxScore");
            uint dxScore = ToUInt(dxScoreValue);
            if (dxScoreValue == null || dxScore == 0)
            {
                object storedDxScore = ReadFirstMember(userScore, "deluxscore", "DxScore", "dxScore");
                uint storedDx = ToUInt(storedDxScore);
                if (storedDxScore != null && storedDx > 0)
                {
                    dxScore = storedDx;
                }
            }
            if (dxScore > 0 || snapshot.DxScore == 0)
            {
                snapshot.DxScore = dxScore;
            }

            object achievementValue = InvokeNoArg(score, "GetAchivement") ??
                                      InvokeNoArg(score, "GetAchievement");
            if (achievementValue != null)
            {
                decimal achievement = ToDecimal(achievementValue);
                if (achievement > 0m || snapshot.Achievement == 0m)
                {
                    snapshot.Achievement = achievement;
                }
            }
            else
            {
                object storedAchievement = ReadFirstMember(
                    userScore, "achivement", "achievement", "Achievement");
                if (storedAchievement != null)
                {
                    decimal achievement = ToDecimal(storedAchievement) / 10000m;
                    if (achievement > 0m || snapshot.Achievement == 0m)
                    {
                        snapshot.Achievement = achievement;
                    }
                }
            }
            snapshot.Rank = RankFromAchievement(snapshot.Achievement);
        }

        private static string RankFromAchievement(decimal achievement)
        {
            if (achievement >= 100.5m) return "SSS+";
            if (achievement >= 100m) return "SSS";
            if (achievement >= 99.5m) return "SS+";
            if (achievement >= 99m) return "SS";
            if (achievement >= 98m) return "S+";
            if (achievement >= 97m) return "S";
            if (achievement >= 94m) return "AAA";
            if (achievement >= 90m) return "AA";
            if (achievement >= 80m) return "A";
            if (achievement >= 75m) return "BBB";
            if (achievement >= 70m) return "BB";
            if (achievement >= 60m) return "B";
            if (achievement >= 50m) return "C";
            return "D";
        }

        private bool TryReadGameplayTime(
            int player,
            out decimal progress,
            out uint elapsedSeconds,
            out uint durationSeconds)
        {
            progress = 0m;
            elapsedSeconds = 0;
            durationSeconds = 0;
            ResolveGameplayTimeMethods();

            if (_notesManagerInstanceMethod == null || _notesCurrentMsecMethod == null ||
                _notesPlayFirstMsecMethod == null || _notesPlayFinalMsecMethod == null)
            {
                return false;
            }

            object notesManager = _notesManagerInstanceMethod.Invoke(null, new object[] { player });
            if (notesManager == null)
            {
                return false;
            }

            decimal currentMsec = ToDecimal(_notesCurrentMsecMethod.Invoke(null, null));
            decimal firstMsec = ToDecimal(_notesPlayFirstMsecMethod.Invoke(notesManager, null));
            decimal finalMsec = ToDecimal(_notesPlayFinalMsecMethod.Invoke(notesManager, null));
            decimal durationMsec = finalMsec - firstMsec;
            if (durationMsec <= 0m)
            {
                return false;
            }

            decimal elapsedMsec = currentMsec - firstMsec;
            if (elapsedMsec < 0m)
            {
                elapsedMsec = 0m;
            }
            else if (elapsedMsec > durationMsec)
            {
                elapsedMsec = durationMsec;
            }

            progress = elapsedMsec / durationMsec;
            elapsedSeconds = (uint)Math.Floor((double)(elapsedMsec / 1000m));
            durationSeconds = (uint)Math.Ceiling((double)(durationMsec / 1000m));
            return true;
        }

        private void ResolveGameplayTimeMethods()
        {
            if (_gameplayTimeResolved)
            {
                return;
            }

            System.Type notesManagerType = AccessTools.TypeByName("Manager.NotesManager");
            if (notesManagerType != null)
            {
                _notesManagerInstanceMethod = notesManagerType.GetMethod(
                    "Instance",
                    BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static,
                    null,
                    new System.Type[] { typeof(int) },
                    null);
                _notesCurrentMsecMethod = FindMethod(notesManagerType, "GetCurrentMsec", true);
                _notesPlayFirstMsecMethod = FindMethod(notesManagerType, "getPlayFirstMsec", false);
                _notesPlayFinalMsecMethod = FindMethod(notesManagerType, "getPlayFinalMsec", false);
            }
            _gameplayTimeResolved = true;
        }

        private void LogSlowPath(string path, long started, ref long lastLog)
        {
            long now = _clock.ElapsedMilliseconds;
            if (now - lastLog < SlowPathLogIntervalMs)
            {
                return;
            }

            double elapsedMs = (Stopwatch.GetTimestamp() - started) * 1000.0 / Stopwatch.Frequency;
            if (elapsedMs < SlowPathThresholdMs)
            {
                return;
            }

            lastLog = now;
            MelonLogger.Warning(
                "XiaoLanMaiBrdge slow " + path + ": " +
                elapsedMs.ToString("0.0", CultureInfo.InvariantCulture) + " ms");
        }

        private static void JudgeResultPostfix(
            int monitorIndex,
            NoteScore.EScoreType type,
            NoteJudge.ETiming timing)
        {
            BridgeMod active = _active;
            if (active != null)
            {
                active.OnJudgeResult(monitorIndex, type, timing);
            }
        }

        private void OnJudgeResult(
            int monitorIndex,
            NoteScore.EScoreType type,
            NoteJudge.ETiming timing)
        {
            if (_server == null || !_server.IsRunning || !GameManager.IsInGame ||
                monitorIndex < 0 || monitorIndex >= 2)
            {
                return;
            }

            long judgeStarted = Stopwatch.GetTimestamp();
            uint track = GameManager.MusicTrackNumber;
            Snapshot counts = _hookCounts[monitorIndex];
            if (counts == null || counts.Track != track)
            {
                counts = new Snapshot { Player = monitorIndex + 1, Track = track };
                _hookCounts[monitorIndex] = counts;
                Snapshot previous = _last[monitorIndex];
                if (_selectedMetadata != null)
                {
                    CopyMetadata(_selectedMetadata, counts);
                }
                else if (previous != null && previous.Track == track)
                {
                    CopyMetadata(previous, counts);
                }
                else
                {
                    ApplyMetadata(counts, monitorIndex);
                }
                ApplyIdentity(counts);
            }

            switch (NoteJudge.ConvertJudge(timing))
            {
                case NoteJudge.JudgeBox.Miss:
                    counts.Miss++;
                    counts.Combo = 0;
                    break;
                case NoteJudge.JudgeBox.Good:
                    counts.Good++;
                    counts.Combo++;
                    break;
                case NoteJudge.JudgeBox.Great:
                    counts.Great++;
                    counts.Combo++;
                    break;
                case NoteJudge.JudgeBox.Perfect:
                    counts.Perfect++;
                    counts.Combo++;
                    break;
                case NoteJudge.JudgeBox.Critical:
                    counts.Critical++;
                    counts.Combo++;
                    break;
                default:
                    return;
            }

            if (!_judgeHookObserved)
            {
                _judgeHookObserved = true;
                MelonLogger.Msg("XiaoLanMaiBrdge received its first live judgement");
            }
            _last[monitorIndex] = counts;
            _judgePublishPending[monitorIndex] = true;
            LogSlowPath("judgement", judgeStarted, ref _lastSlowJudgeLog);
        }

        private void ApplyIdentity(Snapshot snapshot)
        {
            if (string.IsNullOrEmpty(_cachedVersion))
            {
                _cachedVersion = ReadVersion();
            }
            if (IsGuestName(_cachedUserName))
            {
                string userName = ReadUserName();
                _cachedUserName = IsGuestName(userName) ? string.Empty : userName;
            }
            snapshot.Version = _cachedVersion;
            snapshot.UserName = _cachedUserName;
        }

        private static void CopyMetadata(Snapshot source, Snapshot target)
        {
            target.MusicId = source.MusicId;
            target.Difficulty = source.Difficulty;
            target.Title = source.Title;
            target.Artist = source.Artist;
            target.Author = source.Author;
            target.Composer = source.Composer;
            target.Chart = source.Chart;
            target.Level = source.Level;
            target.Constant = source.Constant;
            target.Progress = source.Progress;
            target.ElapsedSeconds = source.ElapsedSeconds;
            target.DurationSeconds = source.DurationSeconds;
        }

        private static void CopyScoreValues(Snapshot source, Snapshot target)
        {
            target.Critical = source.Critical;
            target.Perfect = source.Perfect;
            target.Great = source.Great;
            target.Good = source.Good;
            target.Miss = source.Miss;
            target.Combo = source.Combo;
            target.DxScore = source.DxScore;
            target.Achievement = source.Achievement;
            target.Rank = source.Rank;
        }

        private void ApplyMetadata(Snapshot snapshot, int player)
        {
            try
            {
                System.Type notesManagerType = AccessTools.TypeByName("Manager.NotesManager");
                if (notesManagerType == null)
                {
                    return;
                }

                MethodInfo instanceMethod = notesManagerType.GetMethod(
                    "Instance",
                    BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static,
                    null,
                    new System.Type[] { typeof(int) },
                    null);
                if (instanceMethod == null)
                {
                    return;
                }
                object notesManager = instanceMethod.Invoke(null, new object[] { player });
                if (notesManager == null)
                {
                    return;
                }

                MethodInfo sessionMethod = FindMethod(notesManagerType, "GetSessionInfo", false);
                object session = sessionMethod == null ? null : sessionMethod.Invoke(notesManager, null);
                if (session == null)
                {
                    return;
                }

                snapshot.MusicId = ToInt(ReadMember(session, "musicId"));
                snapshot.Difficulty = ToInt(ReadMember(session, "difficulty"));
                snapshot.Chart = DifficultyName(snapshot.Difficulty);

                object notes = ReadMember(session, "notesData");
                System.Type dataManagerType = AccessTools.TypeByName("Manager.DataManager");
                object dataManager = ReadStaticMember(dataManagerType, "Instance");
                if (dataManager == null)
                {
                    return;
                }

                MethodInfo getMusic = FindMethod(dataManager.GetType(), "GetMusic", false, typeof(int));
                object music = getMusic == null
                    ? null
                    : getMusic.Invoke(dataManager, new object[] { snapshot.MusicId });
                if (music != null)
                {
                    snapshot.Title = ReadStringId(music, "name");
                    snapshot.Composer = ReadStringId(music, "artistName");
                    snapshot.Artist = snapshot.Composer;
                    if (IsUtageMusic(music, snapshot.MusicId))
                    {
                        snapshot.Difficulty = 5;
                        snapshot.Chart = UtageChartName(music);
                    }
                    else
                    {
                        snapshot.Difficulty = ResolveExistingDifficulty(
                            null, music, snapshot.Difficulty);
                        snapshot.Chart = DifficultyName(snapshot.Difficulty);
                    }
                }

                if (notes != null)
                {
                    int musicLevelId = ToInt(ReadMember(notes, "musicLevelID"));
                    MethodInfo getMusicLevel = FindMethod(
                        dataManager.GetType(), "GetMusicLevel", false, typeof(int));
                    object musicLevel = getMusicLevel == null
                        ? null
                        : getMusicLevel.Invoke(dataManager, new object[] { musicLevelId });
                    snapshot.Constant = ToDecimal(ReadMember(notes, "level")) +
                                        ToDecimal(ReadMember(notes, "levelDecimal")) / 10m;
                    snapshot.Author = ReadStringId(notes, "notesDesigner");
                    snapshot.Level = ToText(ReadMember(musicLevel, "levelNum"));
                    if (string.IsNullOrEmpty(snapshot.Level) && snapshot.Constant > 0m)
                    {
                        snapshot.Level = snapshot.Constant.ToString(
                            "0.#", CultureInfo.InvariantCulture);
                    }
                }
            }
            catch (Exception ex)
            {
                if (!_metadataWarningLogged)
                {
                    _metadataWarningLogged = true;
                    Exception detail = ex is TargetInvocationException && ex.InnerException != null
                        ? ex.InnerException
                        : ex;
                    MelonLogger.Warning("XiaoLanMaiBrdge metadata unavailable: " + detail.Message);
                }
            }
        }

        private static MethodInfo FindMethod(
            System.Type type, string name, bool isStatic)
        {
            return FindMethod(type, name, isStatic, 0, null, null);
        }

        private static MethodInfo FindMethod(
            System.Type type, string name, bool isStatic, System.Type argument0)
        {
            return FindMethod(type, name, isStatic, 1, argument0, null);
        }

        private static MethodInfo FindMethod(
            System.Type type,
            string name,
            bool isStatic,
            System.Type argument0,
            System.Type argument1)
        {
            return FindMethod(type, name, isStatic, 2, argument0, argument1);
        }

        private static MethodInfo FindMethod(
            System.Type type,
            string name,
            bool isStatic,
            int argumentCount,
            System.Type argument0,
            System.Type argument1)
        {
            if (type == null || string.IsNullOrEmpty(name))
            {
                return null;
            }

            MethodCacheKey cacheKey = new MethodCacheKey(
                type, name, isStatic, argumentCount, argument0, argument1);
            lock (MemberCacheLock)
            {
                MethodInfo cached;
                if (MethodCache.TryGetValue(cacheKey, out cached))
                {
                    return cached;
                }

                BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic |
                                     (isStatic ? BindingFlags.Static : BindingFlags.Instance);
                System.Type[] arguments;
                if (argumentCount == 0)
                {
                    arguments = System.Type.EmptyTypes;
                }
                else if (argumentCount == 1)
                {
                    arguments = new System.Type[] { argument0 };
                }
                else
                {
                    arguments = new System.Type[] { argument0, argument1 };
                }

                System.Type current = type;
                while (current != null)
                {
                    MethodInfo method = current.GetMethod(name, flags, null, arguments, null);
                    if (method != null)
                    {
                        MethodCache[cacheKey] = method;
                        return method;
                    }
                    current = current.BaseType;
                }

                MethodCache[cacheKey] = null;
                return null;
            }
        }

        private static object ReadMember(object target, string name)
        {
            if (target == null)
            {
                return null;
            }
            MemberInfo member = ResolveMember(target.GetType(), name, false);
            try
            {
                PropertyInfo property = member as PropertyInfo;
                if (property != null)
                {
                    return property.GetValue(target, null);
                }
                FieldInfo field = member as FieldInfo;
                return field == null ? null : field.GetValue(target);
            }
            catch
            {
                return null;
            }
        }

        private static object ReadStaticMember(System.Type type, string name)
        {
            MemberInfo member = ResolveMember(type, name, true);
            try
            {
                PropertyInfo property = member as PropertyInfo;
                if (property != null)
                {
                    return property.GetValue(null, null);
                }
                FieldInfo field = member as FieldInfo;
                return field == null ? null : field.GetValue(null);
            }
            catch
            {
                return null;
            }
        }

        private static MemberInfo ResolveMember(System.Type type, string name, bool isStatic)
        {
            if (type == null || string.IsNullOrEmpty(name))
            {
                return null;
            }

            Dictionary<System.Type, Dictionary<string, MemberInfo>> cache =
                isStatic ? StaticMemberCache : InstanceMemberCache;
            lock (MemberCacheLock)
            {
                Dictionary<string, MemberInfo> members;
                if (!cache.TryGetValue(type, out members))
                {
                    members = new Dictionary<string, MemberInfo>(StringComparer.Ordinal);
                    cache[type] = members;
                }

                MemberInfo cached;
                if (members.TryGetValue(name, out cached))
                {
                    return cached;
                }

                BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic |
                                     (isStatic ? BindingFlags.Static : BindingFlags.Instance);
                System.Type current = type;
                while (current != null)
                {
                    PropertyInfo property = current.GetProperty(name, flags);
                    if (property != null)
                    {
                        members[name] = property;
                        return property;
                    }
                    FieldInfo field = current.GetField(name, flags);
                    if (field != null)
                    {
                        members[name] = field;
                        return field;
                    }
                    current = current.BaseType;
                }

                members[name] = null;
                return null;
            }
        }

        private static string ReadStringId(object target, string name)
        {
            object stringId = ReadMember(target, name);
            if (stringId == null)
            {
                return string.Empty;
            }
            object rawValue = ReadMember(stringId, "str");
            if (rawValue != null)
            {
                return ToText(rawValue);
            }
            return stringId is string ? ToText(stringId) : string.Empty;
        }

        private static int ResolveExistingDifficulty(
            object musicSelectData, object music, int preferredDifficulty)
        {
            int preferred = preferredDifficulty < 0 || preferredDifficulty > 4
                ? 0
                : preferredDifficulty;
            for (int difficulty = preferred; difficulty >= 0; difficulty--)
            {
                if (IsValidNotes(ReadNotesForDifficulty(musicSelectData, music, difficulty)))
                {
                    return difficulty;
                }
            }
            for (int difficulty = preferred + 1; difficulty <= 4; difficulty++)
            {
                if (IsValidNotes(ReadNotesForDifficulty(musicSelectData, music, difficulty)))
                {
                    return difficulty;
                }
            }
            return preferred;
        }

        private static object ReadNotesForDifficulty(
            object musicSelectData, object music, int difficulty)
        {
            object selectedNotes = ReadIndex(
                ReadFirstMember(musicSelectData, "ScoreData", "scoreData"), difficulty);
            if (IsValidNotes(selectedNotes))
            {
                return selectedNotes;
            }
            object musicNotes = ReadIndex(
                ReadFirstMember(music, "notesData", "NotesData", "ScoreData", "scoreData"),
                difficulty);
            return IsValidNotes(musicNotes) ? musicNotes : selectedNotes ?? musicNotes;
        }

        private static bool IsValidNotes(object notes)
        {
            return notes != null &&
                   (ToInt(ReadMember(notes, "musicLevelID")) > 0 ||
                    ToDecimal(ReadMember(notes, "level")) > 0m);
        }

        private static bool IsUtageMusic(object music, int musicId)
        {
            if (music == null)
            {
                return false;
            }
            object genre = ReadMember(music, "genreName");
            int genreId = ToInt(ReadMember(genre, "id"));
            string genreName = ToText(ReadMember(genre, "str"));
            if (genreId == 107 || genreName.Contains("宴会场") || genreName.Contains("宴會場"))
            {
                return true;
            }
            return musicId >= 100000 &&
                   (!string.IsNullOrEmpty(ToText(ReadMember(music, "utageKanjiName"))) ||
                    ReadStringId(music, "name").StartsWith("[", StringComparison.Ordinal));
        }

        private static string UtageChartName(object music)
        {
            string kanji = ToText(ReadMember(music, "utageKanjiName")).Trim();
            return string.IsNullOrEmpty(kanji) ? "UTAGE" : "UTAGE " + kanji;
        }

        private static int ToInt(object value)
        {
            try
            {
                return value == null ? 0 : Convert.ToInt32(value, CultureInfo.InvariantCulture);
            }
            catch
            {
                return 0;
            }
        }

        private static uint ToUInt(object value)
        {
            try
            {
                return value == null ? 0u : Convert.ToUInt32(value, CultureInfo.InvariantCulture);
            }
            catch
            {
                return 0u;
            }
        }

        private static decimal ToDecimal(object value)
        {
            try
            {
                return value == null ? 0m : Convert.ToDecimal(value, CultureInfo.InvariantCulture);
            }
            catch
            {
                return 0m;
            }
        }

        private static string ToText(object value)
        {
            return value == null ? string.Empty : Convert.ToString(value, CultureInfo.InvariantCulture);
        }

        private static string DifficultyName(int difficulty)
        {
            switch (difficulty)
            {
                case 0: return "BASIC";
                case 1: return "ADVANCED";
                case 2: return "EXPERT";
                case 3: return "MASTER";
                case 4: return "Re:MASTER";
                default: return difficulty >= 0 ? "UTAGE" : string.Empty;
            }
        }
    }

    internal sealed class PresenceSnapshot
    {
        public string Status = "MENU";
        public string Version = string.Empty;
        public string UserName = string.Empty;
        public int Remaining;
        public bool TimerInfinite;
        public int MusicId;
        public int DifficultyId = -1;
        public string Difficulty = string.Empty;
        public string Title = string.Empty;
        public string Artist = string.Empty;
        public string Author = string.Empty;
        public string Composer = string.Empty;
        public string Level = string.Empty;
        public decimal Constant;
        public int GameDifficultyId = -1;
        public int CurrentDifficultyId = -1;
        public int SelectDifficultyIndex = -1;
        public int CardDifficultyId = -1;
        public bool IsLevelTab;
        public bool IsExtraFolder;

        public bool SameValues(PresenceSnapshot other)
        {
            return other != null &&
                   Status == other.Status &&
                   Version == other.Version &&
                   UserName == other.UserName &&
                   Remaining == other.Remaining &&
                   TimerInfinite == other.TimerInfinite &&
                   MusicId == other.MusicId &&
                   DifficultyId == other.DifficultyId &&
                   Difficulty == other.Difficulty &&
                   Title == other.Title &&
                   Artist == other.Artist &&
                   Author == other.Author &&
                   Composer == other.Composer &&
                   Level == other.Level &&
                   Constant == other.Constant &&
                   GameDifficultyId == other.GameDifficultyId &&
                   CurrentDifficultyId == other.CurrentDifficultyId &&
                   SelectDifficultyIndex == other.SelectDifficultyIndex &&
                   CardDifficultyId == other.CardDifficultyId &&
                   IsLevelTab == other.IsLevelTab &&
                   IsExtraFolder == other.IsExtraFolder;
        }

        public string ToJson()
        {
            return string.Format(
                CultureInfo.InvariantCulture,
                "{{\"event\":\"presence\",\"status\":\"{0}\",\"version\":\"{1}\",\"user_name\":\"{2}\"," +
                "\"remaining\":{3},\"timer_infinite\":{4},\"music_id\":{5}," +
                "\"difficulty_id\":{6},\"difficulty\":\"{7}\",\"title\":\"{8}\"," +
                "\"artist\":\"{9}\",\"author\":\"{10}\",\"composer\":\"{11}\"," +
                "\"level\":\"{12}\",\"constant\":{13:0.0}," +
                "\"debug_game_difficulty\":{14},\"debug_current_difficulty\":{15}," +
                "\"debug_select_index\":{16},\"debug_card_difficulty\":{17}," +
                "\"debug_level_tab\":{18},\"debug_extra_folder\":{19}}}",
                Snapshot.JsonEscape(Status), Snapshot.JsonEscape(Version), Snapshot.JsonEscape(UserName),
                Remaining, TimerInfinite ? "true" : "false", MusicId, DifficultyId,
                Snapshot.JsonEscape(Difficulty), Snapshot.JsonEscape(Title),
                Snapshot.JsonEscape(Artist), Snapshot.JsonEscape(Author),
                Snapshot.JsonEscape(Composer), Snapshot.JsonEscape(Level), Constant,
                GameDifficultyId, CurrentDifficultyId, SelectDifficultyIndex, CardDifficultyId,
                IsLevelTab ? "true" : "false", IsExtraFolder ? "true" : "false");
        }
    }

    internal sealed class Snapshot
    {
        public int Player;
        public uint Track;
        public uint Critical;
        public uint Perfect;
        public uint Great;
        public uint Good;
        public uint Miss;
        public uint Combo;
        public uint DxScore;
        public decimal Achievement;
        public string Rank = string.Empty;
        public int MusicId;
        public int Difficulty = -1;
        public string Version = string.Empty;
        public string UserName = string.Empty;
        public string Title = string.Empty;
        public string Artist = string.Empty;
        public string Author = string.Empty;
        public string Composer = string.Empty;
        public string Chart = string.Empty;
        public string Level = string.Empty;
        public decimal Constant;
        public decimal Progress;
        public uint ElapsedSeconds;
        public uint DurationSeconds;

        public uint TotalJudgements
        {
            get { return Critical + Perfect + Great + Good + Miss; }
        }

        public bool SameValues(Snapshot other)
        {
            return other != null &&
                   Player == other.Player &&
                   Track == other.Track &&
                   Critical == other.Critical &&
                   Perfect == other.Perfect &&
                   Great == other.Great &&
                   Good == other.Good &&
                   Miss == other.Miss &&
                   Combo == other.Combo &&
                   DxScore == other.DxScore &&
                   Achievement == other.Achievement &&
                   Rank == other.Rank &&
                   MusicId == other.MusicId &&
                   Difficulty == other.Difficulty &&
                   Version == other.Version &&
                   UserName == other.UserName &&
                   Title == other.Title &&
                   Artist == other.Artist &&
                   Author == other.Author &&
                   Composer == other.Composer &&
                   Chart == other.Chart &&
                   Level == other.Level &&
                   Constant == other.Constant &&
                   Progress == other.Progress &&
                   ElapsedSeconds == other.ElapsedSeconds &&
                   DurationSeconds == other.DurationSeconds;
        }

        public string ToJson(string eventName, string status)
        {
            return string.Format(
                CultureInfo.InvariantCulture,
                "{{\"event\":\"{0}\",\"status\":\"{1}\",\"player\":{2},\"track\":{3}," +
                "\"critical\":{4},\"perfect\":{5},\"great\":{6},\"good\":{7},\"miss\":{8}," +
                "\"combo\":{9},\"dx_score\":{10},\"achievement\":{11:0.0000},\"rank\":\"{12}\"," +
                "\"music_id\":{13},\"difficulty_id\":{14},\"version\":\"{15}\",\"user_name\":\"{16}\",\"title\":\"{17}\"," +
                "\"artist\":\"{18}\",\"author\":\"{19}\",\"composer\":\"{20}\",\"chart\":\"{21}\",\"level\":\"{22}\"," +
                "\"constant\":{23:0.0},\"progress\":{24:0.0000}," +
                "\"elapsed_seconds\":{25},\"duration_seconds\":{26}}}",
                eventName, status, Player, Track, Critical, Perfect, Great, Good, Miss,
                Combo, DxScore, Achievement, JsonEscape(Rank), MusicId, Difficulty, JsonEscape(Version),
                JsonEscape(UserName), JsonEscape(Title), JsonEscape(Artist),
                JsonEscape(Author), JsonEscape(Composer), JsonEscape(Chart),
                JsonEscape(Level), Constant, Progress, ElapsedSeconds, DurationSeconds);
        }

        internal static string JsonEscape(string value)
        {
            if (string.IsNullOrEmpty(value))
            {
                return string.Empty;
            }
            StringBuilder result = new StringBuilder(value.Length + 8);
            foreach (char character in value)
            {
                switch (character)
                {
                    case '\\': result.Append("\\\\"); break;
                    case '"': result.Append("\\\""); break;
                    case '\b': result.Append("\\b"); break;
                    case '\f': result.Append("\\f"); break;
                    case '\n': result.Append("\\n"); break;
                    case '\r': result.Append("\\r"); break;
                    case '\t': result.Append("\\t"); break;
                    default:
                        if (character < 32)
                        {
                            result.Append("\\u");
                            result.Append(((int)character).ToString("x4", CultureInfo.InvariantCulture));
                        }
                        else
                        {
                            result.Append(character);
                        }
                        break;
                }
            }
            return result.ToString();
        }
    }

    internal sealed class BridgeConfig
    {
        public bool Enabled = true;
        public int Port = 8891;
        public int PublishIntervalMs = 250;
        public int PresenceIntervalMs = 250;

        public static BridgeConfig Load(string path)
        {
            BridgeConfig config = new BridgeConfig();
            if (!File.Exists(path))
            {
                return config;
            }

            foreach (string raw in File.ReadAllLines(path))
            {
                string line = raw.Trim();
                if (line.Length == 0 || line.StartsWith("#") || line.StartsWith(";"))
                {
                    continue;
                }

                int separator = line.IndexOf('=');
                if (separator <= 0)
                {
                    continue;
                }

                string key = line.Substring(0, separator).Trim();
                string value = line.Substring(separator + 1).Trim();
                int number;

                if (key.Equals("Enabled", StringComparison.OrdinalIgnoreCase))
                {
                    bool enabled;
                    if (bool.TryParse(value, out enabled))
                    {
                        config.Enabled = enabled;
                    }
                }
                else if (key.Equals("Port", StringComparison.OrdinalIgnoreCase) &&
                         int.TryParse(value, out number) && number >= 1024 && number <= 65535)
                {
                    config.Port = number;
                }
                else if (key.Equals("PublishIntervalMs", StringComparison.OrdinalIgnoreCase) &&
                          int.TryParse(value, out number) && number >= 50 && number <= 5000)
                {
                    config.PublishIntervalMs = number;
                }
                else if (key.Equals("PresenceIntervalMs", StringComparison.OrdinalIgnoreCase) &&
                         int.TryParse(value, out number) && number >= 250 && number <= 10000)
                {
                    config.PresenceIntervalMs = number;
                }
            }

            return config;
        }
    }

    internal sealed class SseServer
    {
        private sealed class ClientConnection
        {
            public TcpClient Client;
            public NetworkStream Stream;
        }

        private readonly int _port;
        private readonly object _clientsLock = new object();
        private readonly object _queueLock = new object();
        private readonly List<ClientConnection> _clients = new List<ClientConnection>();
        private readonly Queue<string> _queue = new Queue<string>();
        private readonly AutoResetEvent _wake = new AutoResetEvent(false);
        private readonly UTF8Encoding _utf8 = new UTF8Encoding(false);
        private volatile bool _running;
        private TcpListener _listener;
        private Thread _acceptThread;
        private Thread _sendThread;

        public SseServer(int port)
        {
            _port = port;
        }

        public bool IsRunning
        {
            get { return _running; }
        }

        public void Start()
        {
            if (_running)
            {
                return;
            }

            _listener = new TcpListener(IPAddress.Loopback, _port);
            _listener.Server.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReuseAddress, true);
            _listener.Start();
            _running = true;

            _acceptThread = new Thread(AcceptLoop);
            _acceptThread.IsBackground = true;
            _acceptThread.Name = "XiaoLanMaiBrdge-Accept";
            _acceptThread.Start();

            _sendThread = new Thread(SendLoop);
            _sendThread.IsBackground = true;
            _sendThread.Name = "XiaoLanMaiBrdge-Send";
            _sendThread.Start();
        }

        public void PublishJson(string json)
        {
            if (!_running || string.IsNullOrEmpty(json))
            {
                return;
            }

            lock (_queueLock)
            {
                while (_queue.Count >= 512)
                {
                    _queue.Dequeue();
                }
                _queue.Enqueue("data: " + json + "\n\n");
            }
            _wake.Set();
        }

        public void Stop()
        {
            if (!_running)
            {
                return;
            }

            _running = false;
            _wake.Set();

            try
            {
                _listener.Stop();
            }
            catch
            {
            }

            CloseAllClients();

            if (_acceptThread != null && _acceptThread.IsAlive)
            {
                _acceptThread.Join(1500);
            }
            if (_sendThread != null && _sendThread.IsAlive)
            {
                _sendThread.Join(1500);
            }
        }

        private void AcceptLoop()
        {
            while (_running)
            {
                try
                {
                    TcpClient client = _listener.AcceptTcpClient();
                    ThreadPool.QueueUserWorkItem(InitializeClient, client);
                }
                catch (SocketException)
                {
                    if (!_running)
                    {
                        return;
                    }
                }
                catch (ObjectDisposedException)
                {
                    return;
                }
            }
        }

        private void InitializeClient(object state)
        {
            TcpClient client = (TcpClient)state;
            try
            {
                client.NoDelay = true;
                client.ReceiveTimeout = 3000;
                client.SendTimeout = 1500;
                NetworkStream stream = client.GetStream();
                string request = ReadHeaders(stream, 8192);

                if (!request.StartsWith("GET /events ", StringComparison.Ordinal) &&
                    !request.StartsWith("GET /events?", StringComparison.Ordinal))
                {
                    byte[] notFound = Encoding.ASCII.GetBytes(
                        "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n");
                    stream.Write(notFound, 0, notFound.Length);
                    client.Close();
                    return;
                }

                byte[] response = Encoding.ASCII.GetBytes(
                    "HTTP/1.1 200 OK\r\n" +
                    "Content-Type: text/event-stream; charset=utf-8\r\n" +
                    "Cache-Control: no-cache\r\n" +
                    "Connection: keep-alive\r\n" +
                    "Access-Control-Allow-Origin: *\r\n\r\n");
                stream.Write(response, 0, response.Length);
                byte[] connected = Encoding.ASCII.GetBytes(": connected\n\n");
                stream.Write(connected, 0, connected.Length);

                ClientConnection connection = new ClientConnection { Client = client, Stream = stream };
                lock (_clientsLock)
                {
                    if (!_running)
                    {
                        client.Close();
                        return;
                    }
                    _clients.Add(connection);
                }
            }
            catch
            {
                try
                {
                    client.Close();
                }
                catch
                {
                }
            }
        }

        private void SendLoop()
        {
            Stopwatch heartbeat = Stopwatch.StartNew();
            while (_running)
            {
                _wake.WaitOne(1000, false);
                List<string> frames = new List<string>();
                lock (_queueLock)
                {
                    while (_queue.Count > 0)
                    {
                        frames.Add(_queue.Dequeue());
                    }
                }

                if (heartbeat.ElapsedMilliseconds >= 5000)
                {
                    frames.Add(": heartbeat\n\n");
                    heartbeat.Reset();
                    heartbeat.Start();
                }

                foreach (string frame in frames)
                {
                    Broadcast(frame);
                }
            }
        }

        private void Broadcast(string frame)
        {
            byte[] data = _utf8.GetBytes(frame);
            ClientConnection[] clients;
            lock (_clientsLock)
            {
                clients = _clients.ToArray();
            }

            foreach (ClientConnection connection in clients)
            {
                try
                {
                    connection.Stream.Write(data, 0, data.Length);
                    connection.Stream.Flush();
                }
                catch
                {
                    RemoveClient(connection);
                }
            }
        }

        private void RemoveClient(ClientConnection connection)
        {
            lock (_clientsLock)
            {
                _clients.Remove(connection);
            }
            try
            {
                connection.Client.Close();
            }
            catch
            {
            }
        }

        private void CloseAllClients()
        {
            ClientConnection[] clients;
            lock (_clientsLock)
            {
                clients = _clients.ToArray();
                _clients.Clear();
            }
            foreach (ClientConnection connection in clients)
            {
                try
                {
                    connection.Client.Close();
                }
                catch
                {
                }
            }
        }

        private static string ReadHeaders(NetworkStream stream, int maxBytes)
        {
            MemoryStream buffer = new MemoryStream();
            int previous = -1;
            int beforePrevious = -1;
            int thirdPrevious = -1;

            while (buffer.Length < maxBytes)
            {
                int value = stream.ReadByte();
                if (value < 0)
                {
                    break;
                }
                buffer.WriteByte((byte)value);

                bool lfLf = previous == '\n' && value == '\n';
                bool crlfCrLf = thirdPrevious == '\r' && beforePrevious == '\n' &&
                                  previous == '\r' && value == '\n';
                if (lfLf || crlfCrLf)
                {
                    break;
                }

                thirdPrevious = beforePrevious;
                beforePrevious = previous;
                previous = value;
            }

            return Encoding.ASCII.GetString(buffer.ToArray());
        }
    }
}
