param(
  [string]$Action = "shot",
  [int]$Hwnd = 0,
  [int]$X = 0,
  [int]$Y = 0,
  [string]$Out = "shot.png",
  [string]$Keys = ""
)

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

function Fore([IntPtr]$h) {
  [void][W]::ShowWindow($h, 9)
  try { [System.Windows.Forms.SendKeys]::SendWait("%") } catch {}
  Start-Sleep -Milliseconds 120
  [void][W]::SetForegroundWindow($h)
  try { [System.Windows.Forms.SendKeys]::SendWait("%") } catch {}
  Start-Sleep -Milliseconds 180
}

$sig = @'
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint f, IntPtr e);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
'@
if (-not ("W" -as [type])) { Add-Type -TypeDefinition $sig }

function Shot([IntPtr]$h, [string]$path) {
  $r = New-Object W+RECT
  [void][W]::GetWindowRect($h, [ref]$r)
  $w = $r.R - $r.L; $hgt = $r.B - $r.T
  if ($w -le 0 -or $hgt -le 0) { Write-Output "bad rect"; return }
  $bmp = New-Object System.Drawing.Bitmap $w, $hgt
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $hdc = $g.GetHdc()
  [void][W]::PrintWindow($h, $hdc, 2)
  $g.ReleaseHdc($hdc)
  $g.Dispose()
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  Write-Output ("shot {0} {1}x{2} -> {3}" -f $h, $w, $hgt, $path)
}

switch ($Action) {
  "shot" { Shot ([IntPtr]$Hwnd) $Out }
  "click" {
    Fore ([IntPtr]$Hwnd)
    [void][W]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 60
    [W]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)
    Start-Sleep -Milliseconds 40
    [W]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
    Write-Output ("click {0},{1}" -f $X, $Y)
  }
  "bs" {
    Fore ([IntPtr]$Hwnd)
    for ($i = 0; $i -lt [int]$Keys; $i++) {
      [W]::keybd_event(0x08, 0, 0, [IntPtr]::Zero)
      [W]::keybd_event(0x08, 0, 2, [IntPtr]::Zero)
      Start-Sleep -Milliseconds 15
    }
    Write-Output ("backspace x{0}" -f $Keys)
  }
  "clickrel" {
    Fore ([IntPtr]$Hwnd)
    $pt = New-Object W+POINT
    $pt.X = [int]$X; $pt.Y = [int]$Y
    [void][W]::ClientToScreen([IntPtr]$Hwnd, [ref]$pt)
    [void][W]::SetCursorPos($pt.X, $pt.Y)
    Start-Sleep -Milliseconds 120
    1..2 | ForEach-Object {
      [W]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)
      Start-Sleep -Milliseconds 40
      [W]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
      Start-Sleep -Milliseconds 200
    }
    Write-Output ("clickrel {0},{1} -> {2},{3}" -f $X, $Y, $pt.X, $pt.Y)
  }
  "click2" {
    Fore ([IntPtr]$Hwnd)
    [void][W]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 120
    1..2 | ForEach-Object {
      [W]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)
      Start-Sleep -Milliseconds 50
      [W]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
      Start-Sleep -Milliseconds 250
    }
    Write-Output ("click2 {0},{1}" -f $X, $Y)
  }
  "wheel" {
    Fore ([IntPtr]$Hwnd)
    [void][W]::SetCursorPos($X, $Y)
    Start-Sleep -Milliseconds 150
    $delta = 120 * [int]$Keys
    for ($i = 0; $i -lt [Math]::Abs([int]$Keys); $i++) {
      [W]::mouse_event(0x0800, 0, 0, $delta / [Math]::Abs([int]$Keys) * $null + $(if ([int]$Keys -gt 0) { 120 } else { -120 }), [IntPtr]::Zero)
      Start-Sleep -Milliseconds 60
    }
    Write-Output ("wheel x{0} at {1},{2}" -f $Keys, $X, $Y)
  }
  "sendkeys" {
    Fore ([IntPtr]$Hwnd)
    Start-Sleep -Milliseconds 200
    [System.Windows.Forms.SendKeys]::SendWait($Keys)
    Write-Output ("sendkeys " + $Keys)
  }
  "key" {
    Fore ([IntPtr]$Hwnd)
    foreach ($ch in $Keys.ToCharArray()) {
      $vk = [byte][char]([char]::ToUpper($ch))
      [W]::keybd_event($vk, 0, 0, [IntPtr]::Zero)
      [W]::keybd_event($vk, 0, 2, [IntPtr]::Zero)
    }
    Write-Output ("typed {0}" -f $Keys)
  }
}
