# SetcomQDQ - QDQ-A01 Voltage Controller

A command-line tool for controlling QDQ-A01 power transformers via RS485 Modbus protocol.

## Overview

SetcomQDQ (`setcom.exe`) allows you to set output voltage on QDQ-A01 transformers used for PDLC smart glass control. The tool supports both interactive mode and batch/script operation.

---

## Development Environment Setup

### Prerequisites

1. **Visual Studio Code**
   - Download from: https://code.visualstudio.com/

2. **.NET 10.0 SDK**
   - Download from: https://dotnet.microsoft.com/download/dotnet/10.0
   - Verify installation:
     ```
     dotnet --version
     ```

### Required VS Code Extensions

Install these extensions from the VS Code Extensions marketplace (Ctrl+Shift+X):

1. **C# Dev Kit** (Microsoft)
   - Extension ID: `ms-dotnettools.csdevkit`
   - Provides C# language support, IntelliSense, debugging

2. **C#** (Microsoft)
   - Extension ID: `ms-dotnettools.csharp`
   - Core C# language support (installed with C# Dev Kit)

3. **.NET Install Tool** (Microsoft)
   - Extension ID: `ms-dotnettools.vscode-dotnet-runtime`
   - Manages .NET SDK installations

Optional but recommended:

4. **NuGet Package Manager**
   - Extension ID: `jmrog.vscode-nuget-package-manager`
   - Easy NuGet package management

---

## Building the Project

### Debug Build

```bash
cd SetcomQDQ
dotnet build
```

Output: `bin\Debug\net10.0\setcom.exe`

### Release Build

```bash
cd SetcomQDQ
dotnet build -c Release
```

Output: `bin\Release\net10.0\setcom.exe`

### Creating a Standalone Executable

To create a self-contained executable that doesn't require .NET to be installed:

**Windows x64:**
```bash
dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true
```

**Windows x86:**
```bash
dotnet publish -c Release -r win-x86 --self-contained true -p:PublishSingleFile=true
```

Output: `bin\Release\net10.0\win-x64\publish\setcom.exe`

This creates a single `.exe` file that can run on any Windows machine without .NET installed.

### Trimmed Standalone (Smaller Size)

```bash
dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:PublishTrimmed=true
```

---

## Usage

### Command-Line Mode (Fast/Batch)

```
setcom <COM_PORT> <DEVICE_ID> <VOLTAGE>
```

**Parameters:**
- `COM_PORT` - Serial port (e.g., COM3, COM5)
- `DEVICE_ID` - Device address on RS485 bus (1-6)
- `VOLTAGE` - Target voltage in volts (0.0 - 60.0)

**Examples:**
```bash
setcom COM3 1 45.0    # Set device 1 to 45V
setcom COM3 1 0.0     # Set device 1 to 0V (off)
setcom COM3 2 60.0    # Set device 2 to 60V (max)
```

### Interactive Mode

Run without arguments for guided input:

```bash
setcom
```

You will be prompted for COM port, device ID, and voltage.

### Diagnostic Mode

```bash
setcom test
```

Runs communication diagnostics to verify device connectivity.

---

## Batch Scripts

Two batch files are included for voltage ramping:

### ramp-opaque.bat
Ramps voltage from 0V to 60V over 30 seconds (midpoint: 40V at 15s)

```bash
ramp-opaque.bat
```

### ramp-transparent.bat
Ramps voltage from 60V to 0V over 30 seconds (midpoint: 40V at 15s)

```bash
ramp-transparent.bat
```

Edit the batch files to change `COMPORT` and `DEVICEID` variables if needed.

---

## Hardware Setup

### RS485 Connection

| USB-to-RS485 Adapter | QDQ-A01 |
|---------------------|---------|
| A+ (or D+)          | A       |
| B- (or D-)          | B       |
| GND (if available)  | GND     |

### Communication Settings

- Baud Rate: 9600
- Data Bits: 8
- Parity: None
- Stop Bits: 1
- Flow Control: None

---

## Project Structure

```
SetcomQDQ/
├── Program.cs           # Main entry point
├── QDQA01Protocol.cs    # QDQ-A01 Modbus protocol implementation
├── VoltageSetter.cs     # Voltage control logic
├── SetcomQDQ.csproj     # Project file
├── ramp-opaque.bat      # Voltage ramp script (0V → 60V)
├── ramp-transparent.bat # Voltage ramp script (60V → 0V)
└── README.md            # This file

SetcomCore/              # Shared library
├── Configuration.cs     # Common configuration
├── RS485Controller.cs   # Serial port communication
└── ModbusHelper.cs      # CRC16 and Modbus utilities
```

---

## Troubleshooting

### "Cannot access COM port"
- Another application is using the port
- Check Device Manager to verify COM port number

### No response from device
- Verify wiring (A to A, B to B)
- Try swapping A and B wires
- Check device is powered on
- Run `setcom test` for diagnostics

### Build errors
- Ensure .NET 10.0 SDK is installed
- Run `dotnet restore` to restore packages
