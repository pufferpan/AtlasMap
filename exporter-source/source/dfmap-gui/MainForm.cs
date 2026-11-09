using System.Diagnostics;
using System.Text;
using Dfmap;

namespace DfmapGui;

internal static class GuiProgram
{
    [STAThread]
    private static void Main(string[] args)
    {
        // Smoke test for the embedding path: run a command through the exact capture pipeline the
        // form uses and write the result to a file, so the log plumbing is checkable without
        // clicking anything. `dfmap-gui.exe --selftest [command...]`.
        if (args.Length > 0 && args[0] == "--selftest")
        {
            var cmd = args.Length > 1 ? args[1..] : new[] { "paks" };
            var sb = new StringBuilder();
            var w = new UiWriter(line => sb.AppendLine(line));
            var stdout = Console.Out;
            var stderr = Console.Error;
            Console.SetOut(w);
            Console.SetError(w);
            var code = Program.Execute(cmd);
            w.Flush();
            Console.SetOut(stdout);
            Console.SetError(stderr);
            var path = Path.Combine(AppContext.BaseDirectory, "selftest.log");
            File.WriteAllText(path, $"exit={code}\n\n{sb}");
            return;
        }

        ApplicationConfiguration.Initialize();
        string startupError = null;
        var configIndex = Array.IndexOf(args, "--config");
        if (configIndex >= 0)
        {
            try
            {
                if (configIndex + 1 >= args.Length) throw new ArgumentException("--config 需要一个 JSON 文件路径。");
                Program.UseConfigFile(args[configIndex + 1]);
            }
            catch (Exception ex) { startupError = ex.Message; }
        }
        var smokeIndex = Array.IndexOf(args, "--ui-smoke");
        var form = new MainForm(startupError, smokeIndex >= 0);
        if (smokeIndex >= 0 && smokeIndex + 1 < args.Length)
        {
            form.Shown += (_, _) =>
            {
                var timer = new System.Windows.Forms.Timer { Interval = 600 };
                timer.Tick += (_, _) =>
                {
                    timer.Stop();
                    var path = Path.GetFullPath(args[smokeIndex + 1]);
                    Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                    using var bitmap = new Bitmap(form.Width, form.Height);
                    form.DrawToBitmap(bitmap, new Rectangle(Point.Empty, form.Size));
                    bitmap.Save(path, System.Drawing.Imaging.ImageFormat.Png);
                    form.Close(); timer.Dispose();
                };
                timer.Start();
            };
        }
        Application.Run(form);
    }
}

/// <summary>
/// WinForms front end for exporter.
///
/// It does not reimplement anything: every action calls <see cref="Dfmap.Program.Execute"/> with
/// the same argument vector the CLI would receive, with Console redirected into the log pane. That
/// keeps one implementation of the pipeline and means a bug fixed in the tool is fixed in the UI.
/// </summary>
public sealed class MainForm : Form
{
    private readonly ListBox _maps = new() { Dock = DockStyle.Fill, IntegralHeight = false };
    private readonly TextBox _filter = new() { Dock = DockStyle.Top };
    private readonly RichTextBox _log = new()
    {
        Dock = DockStyle.Fill,
        ReadOnly = true,
        BackColor = Color.FromArgb(24, 24, 28),
        ForeColor = Color.Gainsboro,
        Font = new Font("Consolas", 9f),
        WordWrap = false,
        ScrollBars = RichTextBoxScrollBars.Both,
        DetectUrls = false,
    };
    private readonly TextBox _outDir = new() { Dock = DockStyle.Fill };
    private readonly TextBox _roots = new() { Dock = DockStyle.Fill };
    private readonly TextBox _bbox = new() { Dock = DockStyle.Fill, PlaceholderText = "x0,y0,x1,y1（UE 厘米，按世界原点筛；留空=不过滤）" };
    private readonly TextBox _exclude = new() { Dock = DockStyle.Fill, PlaceholderText = "逗号分隔的关卡路径片段，例如 FarMountains" };
    private readonly NumericUpDown _maxTex = new() { Minimum = 0, Maximum = 8192, Value = 1024, Increment = 256, Width = 90 };
    private readonly CheckBox _plan = new() { Text = "俯视平面图 (--plan)", AutoSize = true };
    private readonly CheckBox _uemodel = new() { Text = "UEFormat .uemodel", AutoSize = true };
    private readonly CheckBox _noTex = new() { Text = "不导出贴图 (--no-textures)", AutoSize = true };
    private readonly CheckBox _all = new() { Text = "不做取舍 (--all)", AutoSize = true };
    private readonly CheckBox _splitExport = new() { Text = "分块 GLB", AutoSize = true, Checked = true };
    private readonly CheckBox _keepBase = new() { Text = "保留普通层与 HD 层", AutoSize = true, Checked = true };
    private readonly CheckBox _deduplicate = new() { Text = "相同摆放去重", AutoSize = true, Checked = true };
    private readonly CheckBox _visibleOnly = new() { Text = "仅可见物件", AutoSize = true };
    private readonly ComboBox _preset = new() { Dock = DockStyle.Fill, DropDownStyle = ComboBoxStyle.DropDownList };
    private readonly TextBox _blender = new() { Dock = DockStyle.Fill };
    private readonly ToolStripStatusLabel _status = new("就绪");
    private readonly ToolStripStatusLabel _elapsed = new("");
    private readonly Button _run = new() { Text = "导出", Width = 110, Height = 30 };
    private readonly Button _cancel = new() { Text = "取消", Width = 70, Height = 30, Enabled = false };
    private readonly Button _mount = new() { Text = "挂载地图", Width = 95, Height = 30 };
    private readonly Button _settings = new() { Text = "资源与配置", Width = 105, Height = 30 };
    private readonly Button _doctor = new() { Text = "导出前检查", Width = 105, Height = 30 };
    private string _configurationPath;
    private SplitContainer _workspaceSplit;
    private readonly bool _smoke;
    private readonly List<(string Label, string[] Roots)> _presets = new();

    private readonly List<string> _allMaps = new();
    private bool _busy;
    private Stopwatch _clock;

    public MainForm(string startupError = null, bool smoke = false)
    {
        _smoke = smoke;
        Text = "dfmap 修正版 2026.10.31 — 地图导出与验证";
        Width = 1280;
        Height = 820;
        MinimumSize = new Size(1100, 700);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 9f);

        _blender.Text = FindBlender() ?? "";
        LoadPresets();
        _filter.TextChanged += (_, _) => ApplyFilter();
        _maps.SelectedIndexChanged += (_, _) => OnMapSelected();

        Controls.Add(BuildLayout());
        _log.AppendText(Welcome());
        if (startupError != null) Append("配置读取失败：" + startupError + "；请点击「资源与配置」重新选择。");
        Shown += (_, _) =>
        {
            if (_preset.SelectedIndex < 0 && _preset.Items.Count > 0) _preset.SelectedIndex = 0;
            if (_workspaceSplit != null)
            {
                _workspaceSplit.Panel1MinSize = 220;
                _workspaceSplit.Panel2MinSize = 560;
                _workspaceSplit.SplitterDistance = 280;
            }
            if (_smoke) return;
            try
            {
                var loaded = Program.CurrentConfiguration();
                _configurationPath = loaded.SourcePath ?? Path.Combine(AppContext.BaseDirectory, "exporter.local.json");
                Append("配置：" + _configurationPath);
                Append("游戏目录：" + loaded.Config.PaksDirectory);
                foreach (var warning in loaded.Warnings) Append("配置提示：" + warning);
                if (Directory.Exists(loaded.Config.PaksDirectory) && File.Exists(loaded.Config.KeyFile)) AutoLoadMaps();
                else _status.Text = "先点击「资源与配置」选择游戏根目录与本地密钥文件";
            }
            catch (Exception ex) { Append("配置读取失败：" + ex.Message); _status.Text = "请点击「资源与配置」修复"; }
        };
    }

    /// <summary>
    /// Mount the paks and fill the map list on startup. Mounting costs a couple of seconds and a
    /// few hundred MB, which is worth paying once so the window is not empty on first open.
    /// </summary>
    private void AutoLoadMaps()
    {
        if (_busy) return;
        _busy = true; SetButtonsEnabled(false); _cancel.Enabled = false;
        _status.Text = "正在挂载 pak…";
        Task.Run(() =>
        {
            try
            {
                var maps = Program.ListMaps();
                BeginInvoke(() =>
                {
                    _allMaps.Clear();
                    _allMaps.AddRange(maps);
                    ApplyFilter();
                    _status.Text = $"已挂载：{maps.Count} 张地图、{Program.SharedProvider().Files.Count:n0} 个虚拟文件";
                    _log.AppendText($"[gui] 已挂载 {maps.Count} 张地图。选一张，根目录会自动填好。\n");
                    _busy = false; SetButtonsEnabled(true);
                });
            }
            catch (Exception ex)
            {
                BeginInvoke(() =>
                {
                    _status.Text = "挂载失败：" + ex.Message;
                    _log.AppendText($"[gui] 挂载失败 {ex.GetType().Name}: {ex.Message}\n");
                    _busy = false; SetButtonsEnabled(true);
                });
            }
        });
    }

    // ------------------------------------------------------------------ layout

    private Control BuildLayout()
    {
        var root = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3 };
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        root.Controls.Add(BuildToolbar(), 0, 0);

        var split = new SplitContainer { Dock = DockStyle.Fill, FixedPanel = FixedPanel.Panel1 };
        _workspaceSplit = split;
        split.Panel1.Controls.Add(BuildMapPane());
        split.Panel2.Controls.Add(BuildRightPane());
        root.Controls.Add(split, 0, 1);

        var strip = new StatusStrip();
        strip.Items.Add(_status);
        strip.Items.Add(new ToolStripStatusLabel { Spring = true });
        strip.Items.Add(_elapsed);
        root.Controls.Add(strip, 0, 2);
        return root;
    }

    private Control BuildToolbar()
    {
        var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, Padding = new Padding(8, 8, 8, 4) };
        panel.Controls.Add(_settings);
        panel.Controls.Add(_doctor);
        panel.Controls.Add(_mount);
        panel.Controls.Add(new Label { Text = "  Blender:", AutoSize = true, Padding = new Padding(0, 8, 0, 0) });
        _blender.Width = 280;
        panel.Controls.Add(_blender);
        var browseBlender = new Button { Text = "…", Width = 30, Height = 24 };
        browseBlender.Click += (_, _) => BrowseForFile(_blender, "选择 blender.exe", "blender.exe|blender.exe|所有文件|*.*");
        panel.Controls.Add(browseBlender);

        var guide = new Button { Text = "教程与踩坑", AutoSize = true, Height = 30 };
        guide.Click += (_, _) => OpenGuide(); panel.Controls.Add(guide);
        _settings.Click += (_, _) => EditConfiguration();
        _doctor.Click += (_, _) => RunCommand(new[] { "doctor", "--out", Path.Combine(DefaultOutRoot(), "doctor.json") }, "导出前检查");
        _mount.Click += (_, _) => AutoLoadMaps();
        return panel;
    }

    private Control BuildMapPane()
    {
        var box = new GroupBox { Text = "地图（Content/Maps 下的目录）", Dock = DockStyle.Fill, Padding = new Padding(6) };
        var stack = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3 };
        stack.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        stack.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        stack.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        _filter.PlaceholderText = "过滤…";
        stack.Controls.Add(new Label { Text = "过滤", AutoSize = true }, 0, 0);
        stack.Controls.Add(_filter, 0, 1);
        stack.Controls.Add(_maps, 0, 2);
        box.Controls.Add(stack);
        return box;
    }

    private Control BuildRightPane()
    {
        var stack = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 2 };
        stack.RowStyles.Add(new RowStyle(SizeType.Absolute, 325));
        stack.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        stack.Controls.Add(BuildOptions(), 0, 0);

        var logBox = new GroupBox { Text = "输出 / 日志", Dock = DockStyle.Fill, Padding = new Padding(6) };
        logBox.Controls.Add(_log);
        stack.Controls.Add(logBox, 0, 1);
        return stack;
    }

    private Control BuildOptions()
    {
        var box = new GroupBox { Text = "导出选项", Dock = DockStyle.Fill, Padding = new Padding(6) };
        var grid = new TableLayoutPanel { Dock = DockStyle.Top, ColumnCount = 3, AutoSize = true };
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));

        void Row(string label, Control field, Control trailing = null)
        {
            var r = grid.RowCount++;
            grid.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            grid.Controls.Add(new Label { Text = label, AutoSize = true, Padding = new Padding(0, 6, 6, 0) }, 0, r);
            grid.Controls.Add(field, 1, r);
            if (trailing is not null) grid.Controls.Add(trailing, 2, r);
        }

        Row("导出方案", _preset);
        Row("输出目录", _outDir, MakeBrowse(_outDir, "选择输出目录", folder: true));
        Row("资源根 --root", _roots);
        Row("范围 --bbox", _bbox);
        Row("排除 --exclude", _exclude);
        Row("贴图边长 --max-tex", _maxTex);

        var flags = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill };
        flags.Controls.AddRange(new Control[] { _splitExport, _keepBase, _deduplicate, _visibleOnly, _plan, _uemodel, _noTex, _all });
        Row("开关", flags);

        _plan.Checked = true;

        var buttons = new FlowLayoutPanel { AutoSize = true, Dock = DockStyle.Fill, Padding = new Padding(0, 4, 0, 0) };
        var openOut = new Button { Text = "打开输出目录", Width = 110, Height = 30 };
        openOut.Click += (_, _) => OpenPath(_outDir.Text);
        var openBlender = new Button { Text = "用 Blender 打开", Width = 120, Height = 30 };
        openBlender.Click += (_, _) => OpenInBlender();
        var copyCmd = new Button { Text = "复制命令行", Width = 100, Height = 30 };
        copyCmd.Click += (_, _) => CopyCommand();
        var preview = new Button { Text = "预览层清单", Width = 110, Height = 30 };
        preview.Click += (_, _) => { var args = BuildExportArgs(); if (args != null) RunCommand(args.Concat(new[] { "--stats" }).ToArray(), "预览层清单"); };
        buttons.Controls.AddRange(new Control[] { _run, _cancel, preview, openOut, openBlender, copyCmd });
        Row("", buttons);

        _run.Click += (_, _) => StartExport();
        _preset.SelectedIndexChanged += (_, _) => ApplyPreset();
        _cancel.Click += (_, _) =>
        {
            Program.CancelRequested = true;
            _status.Text = "正在取消…";
        };
        box.Controls.Add(grid);
        return box;
    }

    private static Button MakeBrowse(TextBox target, string title, string filter = null, bool folder = false)
    {
        var b = new Button { Text = "…", Width = 30, Height = 24 };
        b.Click += (_, _) =>
        {
            if (folder)
            {
                using var dlg = new FolderBrowserDialog { Description = title };
                if (Directory.Exists(target.Text)) dlg.SelectedPath = target.Text;
                if (dlg.ShowDialog() == DialogResult.OK) target.Text = dlg.SelectedPath;
            }
            else BrowseForFile(target, title, filter);
        };
        return b;
    }

    private static void BrowseForFile(TextBox target, string title, string filter)
    {
        using var dlg = new OpenFileDialog { Title = title, Filter = filter };
        if (dlg.ShowDialog() == DialogResult.OK) target.Text = dlg.FileName;
    }

    // ------------------------------------------------------------------ behaviour

    private void ApplyFilter()
    {
        var needle = _filter.Text.Trim();
        _maps.BeginUpdate();
        _maps.Items.Clear();
        foreach (var m in _allMaps)
            if (needle.Length == 0 || m.Contains(needle, StringComparison.OrdinalIgnoreCase))
                _maps.Items.Add(m);
        _maps.EndUpdate();
    }

    private void OnMapSelected()
    {
        if (_maps.SelectedItem is not string map) return;
        var safe = map.Replace('\\', '_').Replace('/', '_');
        if (_outDir.Text.Length == 0 || _outDir.Text.StartsWith(DefaultOutRoot(), StringComparison.OrdinalIgnoreCase))
            _outDir.Text = Path.Combine(DefaultOutRoot(), safe);
        if (_roots.Text.Length == 0 || _roots.Text.Contains("Content/Maps/"))
            _roots.Text = $"待查询：{map}";
        BeginQueryRoots(map);
    }

    private static string DefaultOutRoot() => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "atlasmap-exports");

    private void BeginQueryRoots(string map)
    {
        if (_preset.SelectedIndex > 0) { ApplyPreset(); return; }
        if (_busy) return;
        _busy = true; SetButtonsEnabled(false); _cancel.Enabled = false;
        Task.Run(() =>
        {
            try
            {
                var roots = Program.SuggestRoots(map);
                BeginInvoke(() =>
                {
                    if (_maps.SelectedItem as string == map)
                        _roots.Text = string.Join(",", roots);
                    _busy = false; SetButtonsEnabled(true);
                });
            }
            catch (Exception ex)
            {
                BeginInvoke(() => { _status.Text = "查询根目录失败：" + ex.Message; _busy = false; SetButtonsEnabled(true); });
            }
        });
    }

    private string[] BuildExportArgs()
    {
        if (_maps.SelectedItem is not string map)
        {
            MessageBox.Show(this, "先在左边选一张地图。", "dfmap", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return null;
        }
        if (_outDir.Text.Trim().Length == 0)
        {
            MessageBox.Show(this, "要先指定输出目录。", "dfmap", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return null;
        }
        var args = new List<string> { "merge", map, _outDir.Text.Trim() };
        if (_roots.Text.Trim().Length > 0 && !_roots.Text.StartsWith("待查询"))
            args.AddRange(new[] { "--root", _roots.Text.Trim() });
        if (_bbox.Text.Trim().Length > 0) args.AddRange(new[] { "--bbox", _bbox.Text.Trim() });
        if (_exclude.Text.Trim().Length > 0) args.AddRange(new[] { "--exclude", _exclude.Text.Trim() });
        if (_plan.Checked) args.Add("--plan");
        if (_uemodel.Checked) args.Add("--uemodel");
        if (_noTex.Checked) args.Add("--no-textures");
        else args.AddRange(new[] { "--max-tex", ((int)_maxTex.Value).ToString() });
        if (_all.Checked) args.Add("--all");
        if (_splitExport.Checked) args.AddRange(new[] { "--split", "--no-scene" });
        if (_keepBase.Checked) args.Add("--keep-base-with-hd");
        if (_deduplicate.Checked) args.Add("--deduplicate");
        if (_visibleOnly.Checked) args.Add("--visible-only");
        return args.ToArray();
    }

    private void StartExport()
    {
        var args = BuildExportArgs(); if (args == null) return;
        if (File.Exists(Path.Combine(_outDir.Text, "scene.json")) || Directory.Exists(Path.Combine(_outDir.Text, "split")))
        {
            _outDir.Text = Path.Combine(_outDir.Text, "run_" + DateTime.Now.ToString("yyyyMMdd_HHmmss_fff"));
            Append("已有导出保留，本次输出到新目录：" + _outDir.Text);
            args = BuildExportArgs();
        }
        RunCommand(args, "导出 " + _maps.SelectedItem);
    }

    /// <summary>
    /// Runs a command on a worker thread with Console redirected into the log pane. The UI stays
    /// responsive because the pipeline only ever blocks its own thread.
    /// </summary>
    private void RunCommand(string[] args, string label)
    {
        if (_busy) return;
        _busy = true;
        Program.CancelRequested = false;
        SetButtonsEnabled(false);
        _status.Text = label + " …";
        _log.AppendText($"\n===== dfmap {string.Join(' ', args)} =====\n");

        var writer = new UiWriter(line => Append(line));
        _clock = Stopwatch.StartNew();
        var timer = new System.Windows.Forms.Timer { Interval = 500 };
        timer.Tick += (_, _) => _elapsed.Text = _clock.Elapsed.ToString(@"mm\:ss");
        timer.Start();

        Task.Run(() =>
        {
            var stdout = Console.Out;
            var stderr = Console.Error;
            int code;
            try
            {
                Console.SetOut(writer);
                Console.SetError(writer);
                code = Program.Execute(args);
            }
            catch (Exception ex)
            {
                writer.WriteLine($"[gui] {ex.GetType().Name}: {ex.Message}");
                code = -1;
            }
            finally
            {
                Console.SetOut(stdout);
                Console.SetError(stderr);
                writer.Flush();
            }
            BeginInvoke(() =>
            {
                timer.Stop();
                _clock.Stop();
                _busy = false;
                SetButtonsEnabled(true);
                _status.Text = code == 0 ? $"{label} 完成（{_clock.Elapsed:hh\\:mm\\:ss}）"
                             : code == 130 ? $"{label} 已取消"
                             : $"{label} 结束，退出码 {code}";
            });
        });
    }

    private void SetButtonsEnabled(bool enabled)
    {
        _run.Enabled = enabled;
        _mount.Enabled = enabled;
        _settings.Enabled = enabled; _doctor.Enabled = enabled;
        _maps.Enabled = enabled; _filter.Enabled = enabled; _preset.Enabled = enabled;
        _roots.Enabled = enabled; _outDir.Enabled = enabled; _bbox.Enabled = enabled; _exclude.Enabled = enabled;
        _cancel.Enabled = !enabled;
        UseWaitCursor = !enabled;
    }

    private void Append(string line)
    {
        if (InvokeRequired) { BeginInvoke(() => Append(line)); return; }
        _log.AppendText(line + "\n");
        if (_log.Lines.Length > 6000)
        {
            // keep the pane bounded without fighting the caret
            var keep = _log.Lines[^4000..];
            _log.Lines = keep;
        }
        _log.SelectionStart = _log.TextLength;
        _log.ScrollToCaret();
        if (line.StartsWith("  extracted") || line.StartsWith("[textures]") || line.StartsWith("== "))
            _status.Text = line.Trim();
    }

    private void OpenPath(string path)
    {
        try
        {
            if (!Directory.Exists(path)) { MessageBox.Show(this, "目录还不存在：" + path); return; }
            Process.Start(new ProcessStartInfo("explorer.exe", $"\"{path}\"") { UseShellExecute = true });
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message); }
    }

    private void OpenInBlender()
    {
        var glb = Path.Combine(_outDir.Text.Trim(), "scene.glb");
        var split = Path.Combine(_outDir.Text.Trim(), "split");
        var input = File.Exists(Path.Combine(split, "manifest.json")) ? split : glb;
        if (!File.Exists(glb) && input != split) { MessageBox.Show(this, "还没有分块清单或 scene.glb，先导出。"); return; }
        var blender = _blender.Text.Trim();
        if (blender.Length == 0 || !File.Exists(blender))
        {
            BrowseForFile(_blender, "选择 blender.exe", "blender.exe|blender.exe|所有文件|*.*");
            blender = _blender.Text.Trim();
            if (!File.Exists(blender)) return;
        }
        var script = FindSupportFile(Path.Combine("scripts", "blender_import_verified.py"));
        if (script == null) { MessageBox.Show(this, "找不到 scripts/blender_import_verified.py，请保留完整工具目录。"); return; }
        try
        {
            var start = new ProcessStartInfo(blender) { UseShellExecute = false };
            foreach (var argument in new[] { "--factory-startup", "--python-exit-code", "1", "--python", script, "--", input }) start.ArgumentList.Add(argument);
            Process.Start(start);
            _status.Text = "已启动 Blender";
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message); }
    }

    private void CopyCommand()
    {
        var args = BuildExportArgs(); if (args == null) return;
        var quoted = new List<string> { ".\\map-export.exe" };
        if (_configurationPath != null) quoted.AddRange(new[] { "--config", QuotePowerShell(_configurationPath) });
        quoted.AddRange(args.Select(QuotePowerShell));
        var cmd = "& " + string.Join(' ', quoted);
        Clipboard.SetText(cmd);
        _log.AppendText($"\n[已复制]\n{cmd}\n");
    }

    private static string FindBlender()
    {
        foreach (var p in new[]
                 {
                     @"G:\SteamLibrary\steamapps\common\Blender\blender.exe",
                     @"D:\blender\Blender 5.2\blender.exe",
                     @"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
                     @"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe",
                 })
            if (File.Exists(p)) return p;
        return null;
    }

    private static string Welcome() =>
        "dfmap 修正版 2026.10.31\n" +
        "  1. 在「资源与配置」选择同一版本的游戏根目录和本地密钥 JSON；用「导出前检查」生成诊断报告。\n" +
        "  2. 选择地图与方案，先「预览层清单」确认来源。Iceland 分阶段方案只负责对应基础导出，完整修复流程见教程。\n" +
        "  3. 默认分块 GLB、保留源隐藏数据与普通/HD 层，再按完整材质与显示状态去重；不同地图的 HD 层必须逐图核对。\n" +
        "  4. GLB 图像嵌入文件；目录清单、验证记录和特殊纹理原始文件仍应一起保留。\n" +
        "  5. 「用 Blender 打开」会启动独立 Blender，按源元数据恢复隐藏状态并生成验证记录。\n";

    private static string QuotePowerShell(string value) => "'" + value.Replace("'", "''") + "'";

    private static string FindSupportFile(string relative)
    {
        for (var d = new DirectoryInfo(AppContext.BaseDirectory); d != null; d = d.Parent)
        {
            var candidate = Path.Combine(d.FullName, relative);
            if (File.Exists(candidate)) return candidate;
        }
        return null;
    }

    private void OpenGuide()
    {
        var path = FindSupportFile(Path.Combine("docs", "README.md"));
        if (path == null) { MessageBox.Show(this, "教程未找到，请保留工具随附的 docs 目录。"); return; }
        try { Process.Start(new ProcessStartInfo(path) { UseShellExecute = true }); }
        catch (System.ComponentModel.Win32Exception)
        {
            var start = new ProcessStartInfo("explorer.exe") { UseShellExecute = false };
            start.ArgumentList.Add(Path.GetDirectoryName(path)!); Process.Start(start);
        }
    }

    private void EditConfiguration()
    {
        if (_busy) return;
        GameConfig config;
        try
        {
            var loaded = Program.CurrentConfiguration(); config = loaded.Config;
            _configurationPath = loaded.SourcePath ?? Path.Combine(AppContext.BaseDirectory, "exporter.local.json");
        }
        catch { config = new GameConfig(); _configurationPath ??= Path.Combine(AppContext.BaseDirectory, "exporter.local.json"); }
        using var dialog = new ConfigurationDialog(config, _configurationPath);
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            ConfigService.Save(_configurationPath, dialog.Configuration);
            Program.UseConfigFile(_configurationPath, resetSharedProvider: true);
            _allMaps.Clear(); _maps.Items.Clear();
            Append("已保存配置：" + _configurationPath);
            AutoLoadMaps();
        }
        catch (Exception ex) { MessageBox.Show(this, ex.Message, "配置保存失败"); }
    }

    private void LoadPresets()
    {
        _presets.Add(("通用：手动核对资源根", Array.Empty<string>()));
        try
        {
            var path = FindSupportFile(Path.Combine("presets", "Iceland_verified_layers.json"));
            if (path != null)
            {
                using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(path));
                foreach (var stage in doc.RootElement.GetProperty("stages").EnumerateArray())
                    _presets.Add((stage.GetProperty("label").GetString()!, stage.GetProperty("roots").EnumerateArray().Select(x => x.GetString()!).ToArray()));
            }
        }
        catch { /* Manual export remains available if no preset is installed. */ }
        _preset.Items.AddRange(_presets.Select(x => (object)x.Label).ToArray());
        _preset.SelectedIndex = 0;
    }

    private void ApplyPreset()
    {
        if (_preset.SelectedIndex <= 0) return;
        if (_maps.SelectedItem is string map && !string.Equals(map, "Iceland", StringComparison.OrdinalIgnoreCase))
        {
            _preset.SelectedIndex = 0; Append("Iceland 专用方案不能应用到其他地图。"); return;
        }
        _roots.Text = string.Join(',', _presets[_preset.SelectedIndex].Roots);
        _keepBase.Checked = true; _deduplicate.Checked = true;
        _status.Text = "Iceland 分阶段导出；完整地图还需教程中的补层、材质和验证步骤";
    }
}

/// <summary>Console replacement that hands complete lines to the form.</summary>
internal sealed class UiWriter : TextWriter
{
    private readonly Action<string> _sink;
    private readonly StringBuilder _pending = new();

    public UiWriter(Action<string> sink) => _sink = sink;

    public override Encoding Encoding => Encoding.UTF8;

    public override void Write(char value)
    {
        if (value == '\n') { Flush(); return; }
        if (value == '\r') return;
        _pending.Append(value);
        if (_pending.Length > 4096) Flush();          // a progress line with no newline must not stall
    }

    public override void Write(string value)
    {
        if (value is null) return;
        foreach (var c in value) Write(c);
    }

    public override void WriteLine(string value)
    {
        Write(value);
        Flush();
    }

    public override void Flush()
    {
        if (_pending.Length == 0) return;
        var line = _pending.ToString();
        _pending.Clear();
        _sink(line);
    }
}
