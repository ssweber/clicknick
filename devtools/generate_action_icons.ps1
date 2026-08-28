$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing

$outputDirectory = Join-Path $PSScriptRoot "..\src\clicknick\resources\action_icons"
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

$size = 24
$scale = 4
$canvasSize = $size * $scale

function New-IconCanvas {
    $bitmap = [System.Drawing.Bitmap]::new($canvasSize, $canvasSize)
    $bitmap.SetResolution(96 * $scale, 96 * $scale)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.Clear([System.Drawing.Color]::Transparent)
    return @($bitmap, $graphics)
}

function New-IconPen([string] $color, [float] $width = 2) {
    $pen = [System.Drawing.Pen]::new(
        [System.Drawing.ColorTranslator]::FromHtml($color),
        $width * $scale
    )
    $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.LineJoin = [System.Drawing.Drawing2D.LineJoin]::Round
    return $pen
}

function Convert-Point([float] $x, [float] $y) {
    return [System.Drawing.PointF]::new($x * $scale, $y * $scale)
}

function Save-Icon($bitmap, $graphics, [string] $name) {
    $graphics.Dispose()
    $destination = Join-Path $outputDirectory "$name.png"
    $icon = [System.Drawing.Bitmap]::new($size, $size)
    $icon.SetResolution(96, 96)
    $iconGraphics = [System.Drawing.Graphics]::FromImage($icon)
    $iconGraphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
    $iconGraphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $iconGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $iconGraphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $iconGraphics.DrawImage($bitmap, 0, 0, $size, $size)
    $iconGraphics.Dispose()
    $icon.Save($destination, [System.Drawing.Imaging.ImageFormat]::Png)
    $icon.Dispose()
    $bitmap.Dispose()
    Write-Host "Generated $destination"
}

function Add-RoundedRectangle($graphics, $pen, [float] $x, [float] $y, [float] $width, [float] $height, [float] $radius) {
    $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $diameter = 2 * $radius * $scale
    $left = $x * $scale
    $top = $y * $scale
    $right = ($x + $width) * $scale
    $bottom = ($y + $height) * $scale
    $path.AddArc($left, $top, $diameter, $diameter, 180, 90)
    $path.AddArc($right - $diameter, $top, $diameter, $diameter, 270, 90)
    $path.AddArc($right - $diameter, $bottom - $diameter, $diameter, $diameter, 0, 90)
    $path.AddArc($left, $bottom - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    $graphics.DrawPath($pen, $path)
    $path.Dispose()
}

$blue = "#3B8ED0"
$green = "#2E9638"
$orange = "#E87500"

# Address Editor: address book with contact silhouette.
$canvas = New-IconCanvas
$bitmap = $canvas[0]
$graphics = $canvas[1]
$pen = New-IconPen $blue
Add-RoundedRectangle $graphics $pen 6 3 14 18 2
$graphics.DrawLine($pen, (Convert-Point 6 7), (Convert-Point 3.5 7))
$graphics.DrawLine($pen, (Convert-Point 6 12), (Convert-Point 3.5 12))
$graphics.DrawLine($pen, (Convert-Point 6 17), (Convert-Point 3.5 17))
$graphics.DrawEllipse($pen, 10 * $scale, 6 * $scale, 5 * $scale, 5 * $scale)
$graphics.DrawArc($pen, 8.5 * $scale, 11.5 * $scale, 8 * $scale, 7 * $scale, 195, 150)
$pen.Dispose()
Save-Icon $bitmap $graphics "address_editor"

# Data View: compact table/grid.
$canvas = New-IconCanvas
$bitmap = $canvas[0]
$graphics = $canvas[1]
$pen = New-IconPen $blue
Add-RoundedRectangle $graphics $pen 3 4 18 16 1.5
$graphics.DrawLine($pen, (Convert-Point 3 9), (Convert-Point 21 9))
$graphics.DrawLine($pen, (Convert-Point 3 14.5), (Convert-Point 21 14.5))
$graphics.DrawLine($pen, (Convert-Point 9 9), (Convert-Point 9 20))
$graphics.DrawLine($pen, (Convert-Point 15 9), (Convert-Point 15 20))
$pen.Dispose()
Save-Icon $bitmap $graphics "data_view"

# Check Program: search/inspection magnifier.
$canvas = New-IconCanvas
$bitmap = $canvas[0]
$graphics = $canvas[1]
$pen = New-IconPen $green 2.2
$graphics.DrawEllipse($pen, 3 * $scale, 3 * $scale, 12.5 * $scale, 12.5 * $scale)
$graphics.DrawLine($pen, (Convert-Point 14.3 14.3), (Convert-Point 21 21))
$pen.Dispose()
Save-Icon $bitmap $graphics "check_program"

# Console: dark terminal tile with a green prompt.
$canvas = New-IconCanvas
$bitmap = $canvas[0]
$graphics = $canvas[1]
$tilePath = [System.Drawing.Drawing2D.GraphicsPath]::new()
$tilePen = New-IconPen "#343A40" 1.5
Add-RoundedRectangle $graphics $tilePen 2.5 4 19 16 2
$tileBrush = [System.Drawing.SolidBrush]::new([System.Drawing.ColorTranslator]::FromHtml("#343A40"))
$graphics.FillRectangle($tileBrush, 4 * $scale, 5.5 * $scale, 16 * $scale, 13 * $scale)
$pen = New-IconPen $green 1.8
$graphics.DrawLine($pen, (Convert-Point 7 9), (Convert-Point 10.5 12))
$graphics.DrawLine($pen, (Convert-Point 10.5 12), (Convert-Point 7 15))
$graphics.DrawLine($pen, (Convert-Point 13 15), (Convert-Point 17 15))
$pen.Dispose()
$tilePen.Dispose()
$tileBrush.Dispose()
$tilePath.Dispose()
Save-Icon $bitmap $graphics "console"

# Rung Apply: upload/apply arrow.
$canvas = New-IconCanvas
$bitmap = $canvas[0]
$graphics = $canvas[1]
$pen = New-IconPen $orange 2.1
$graphics.DrawLine($pen, (Convert-Point 12 16), (Convert-Point 12 4))
$graphics.DrawLine($pen, (Convert-Point 12 4), (Convert-Point 7.5 8.5))
$graphics.DrawLine($pen, (Convert-Point 12 4), (Convert-Point 16.5 8.5))
$graphics.DrawLine($pen, (Convert-Point 5 15), (Convert-Point 5 20))
$graphics.DrawLine($pen, (Convert-Point 5 20), (Convert-Point 19 20))
$graphics.DrawLine($pen, (Convert-Point 19 20), (Convert-Point 19 15))
$pen.Dispose()
Save-Icon $bitmap $graphics "rung_apply"

# Reload from CLICK: two conventional clockwise refresh arcs.
$canvas = New-IconCanvas
$bitmap = $canvas[0]
$graphics = $canvas[1]
$pen = New-IconPen $orange 2.1
$graphics.DrawBezier(
    $pen,
    (Convert-Point 20.5 11),
    (Convert-Point 20 5.5),
    (Convert-Point 14 1.5),
    (Convert-Point 8 4.5)
)
$graphics.DrawBezier(
    $pen,
    (Convert-Point 8 4.5),
    (Convert-Point 6 5.3),
    (Convert-Point 4.7 6.5),
    (Convert-Point 4 8.5)
)
$graphics.DrawLine($pen, (Convert-Point 4 8.5), (Convert-Point 4 3.5))
$graphics.DrawLine($pen, (Convert-Point 4 8.5), (Convert-Point 9 8.5))
$graphics.DrawBezier(
    $pen,
    (Convert-Point 3.5 13),
    (Convert-Point 4 18.5),
    (Convert-Point 10 22.5),
    (Convert-Point 16 19.5)
)
$graphics.DrawBezier(
    $pen,
    (Convert-Point 16 19.5),
    (Convert-Point 18 18.7),
    (Convert-Point 19.3 17.5),
    (Convert-Point 20 15.5)
)
$graphics.DrawLine($pen, (Convert-Point 20 15.5), (Convert-Point 20 20.5))
$graphics.DrawLine($pen, (Convert-Point 20 15.5), (Convert-Point 15 15.5))
$pen.Dispose()
Save-Icon $bitmap $graphics "reload_from_click"
