using Dfmap;

namespace DfmapGui;

/// <summary>Edits paths through the same validated serializer as the CLI.</summary>
internal sealed class ConfigurationDialog : Form
{
    private readonly TextBox _game = new() { Dock = DockStyle.Fill };
    private readonly TextBox _keys = new() { Dock = DockStyle.Fill };
    private readonly GameConfig _config;
    public GameConfig Configuration { get; private set; }

    public ConfigurationDialog(GameConfig config, string configPath)
    {
        _config = config;
        Text = "资源与配置";
        Width = 780; Height = 300;
        MinimumSize = new Size(620, 280);
        StartPosition = FormStartPosition.CenterParent;
        Font = new Font("Microsoft YaHei UI", 9f);
        _game.Text = config.PaksDirectory ?? "";
        _keys.Text = config.KeyFile ?? "";
        var grid = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(14), ColumnCount = 3, RowCount = 5 };
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        void Row(int row, string title, Control input, Button button = null)
        {
            grid.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            grid.Controls.Add(new Label { Text = title, AutoSize = true, Padding = new Padding(0, 5, 8, 8) }, 0, row);
            grid.Controls.Add(input, 1, row);
            if (button != null) grid.Controls.Add(button, 2, row);
        }
        var gameBrowse = new Button { Text = "选择目录", AutoSize = true };
        gameBrowse.Click += (_, _) => { using var d = new FolderBrowserDialog { Description = "选择当前版本游戏根目录" }; if (Directory.Exists(_game.Text)) d.SelectedPath = _game.Text; if (d.ShowDialog(this) == DialogResult.OK) _game.Text = d.SelectedPath; };
        var keyBrowse = new Button { Text = "选择文件", AutoSize = true };
        keyBrowse.Click += (_, _) => { using var d = new OpenFileDialog { Title = "选择本地密钥 JSON", Filter = "JSON 文件|*.json|所有文件|*.*" }; if (d.ShowDialog(this) == DialogResult.OK) _keys.Text = d.FileName; };
        Row(0, "游戏根目录", _game, gameBrowse);
        Row(1, "本地密钥 JSON", _keys, keyBrowse);
        Row(2, "读取配置", new TextBox { Text = configPath, ReadOnly = true, Dock = DockStyle.Fill });
        var note = new Label { Text = "正式服与体验服分别选择对应目录。扫描包含补丁的游戏根目录；配置只记录密钥文件路径。", AutoSize = true, MaximumSize = new Size(650, 0), Padding = new Padding(0, 8, 0, 8) };
        grid.Controls.Add(note, 0, 3); grid.SetColumnSpan(note, 3);
        var buttons = new FlowLayoutPanel { AutoSize = true, FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Fill };
        var save = new Button { Text = "保存并使用", AutoSize = true };
        var cancel = new Button { Text = "取消", DialogResult = DialogResult.Cancel, AutoSize = true };
        save.Click += (_, _) =>
        {
            try
            {
                var game = ConfigService.NormalizePath(_game.Text);
                var keys = ConfigService.NormalizePath(_keys.Text);
                if (!Directory.Exists(game)) throw new DirectoryNotFoundException("游戏根目录不存在。请选择当前正式服或体验服的实际目录。");
                if (!File.Exists(keys)) throw new FileNotFoundException("密钥文件不存在。请选择本地 JSON 文件。");
                _config.PaksDirectory = game; _config.KeyFile = keys;
                _config.Game = "GAME_DeltaForce"; _config.Recursive = true;
                Configuration = _config;
                DialogResult = DialogResult.OK; Close();
            }
            catch (Exception ex) { MessageBox.Show(this, ex.Message, "配置未保存", MessageBoxButtons.OK, MessageBoxIcon.Information); }
        };
        buttons.Controls.AddRange(new Control[] { save, cancel });
        grid.Controls.Add(buttons, 0, 4); grid.SetColumnSpan(buttons, 3);
        Controls.Add(grid); AcceptButton = save; CancelButton = cancel;
    }
}
