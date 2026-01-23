using System;
using System.IO;
using System.Threading.Tasks;
using SetcomCore;

namespace SetcomQDQ
{
    class Program
    {
        static async Task Main(string[] args)
        {
            if (args.Length > 0 && args[0].ToLower() == "test")
            {
                await RunDiagnosticMode();
                return;
            }

            // Normal operation (voltage control)
            var config = ParseCommandLineArguments(args);
            if (config == null)
            {
                PrintUsage();
                return;
            }

            if (!config.IsValidDeviceId())
            {
                Console.WriteLine($"Error: Device ID must be between 1 and 6. Provided: {config.DeviceId}");
                return;
            }

            // Get target voltage from arguments or interactive input
            double targetVoltage;

            if (args.Length >= 3)
            {
                // Command-line mode
                if (!double.TryParse(args[2], out targetVoltage))
                {
                    Console.WriteLine($"Error: Invalid target voltage: {args[2]}");
                    return;
                }
            }
            else
            {
                // Interactive mode
                Console.WriteLine("Configuration:");
                Console.WriteLine($"  COM Port: {config.ComPort}");
                Console.WriteLine($"  Device ID: {config.DeviceId}");
                Console.WriteLine($"  Baud Rate: {config.BaudRate}");
                Console.WriteLine($"  Max Voltage: {config.MaxVoltage}V");
                Console.WriteLine();

                Console.Write("Enter target voltage (V): ");
                if (!double.TryParse(Console.ReadLine(), out targetVoltage))
                {
                    Console.WriteLine("Invalid voltage value");
                    return;
                }
            }

            // Validate inputs
            if (targetVoltage > config.MaxVoltage)
            {
                Console.WriteLine($"Error: Target voltage {targetVoltage}V exceeds maximum {config.MaxVoltage}V");
                return;
            }

            if (targetVoltage < 0)
            {
                Console.WriteLine("Error: Target voltage cannot be negative");
                return;
            }

            // Initialize components
            using (var rs485 = new RS485Controller(config))
            {
                var protocol = new QDQA01Protocol(config.DeviceId);

                try
                {
                    rs485.Open();
                    await Task.Delay(50);

                    // Fast mode for batch/script operation (all 3 args provided)
                    if (args.Length >= 3)
                    {
                        // Just send the voltage command directly, no extra steps
                        byte[] command = protocol.BuildSetVoltageCommand(targetVoltage);
                        rs485.SendCommand(command);

                        // Brief wait for command to be sent
                        await Task.Delay(50);

                        // Try to read response but don't fail if timeout
                        try
                        {
                            byte[] response = rs485.ReadResponse(8, 300);
                            if (protocol.ValidateResponse(response))
                            {
                                Console.WriteLine($"OK: {targetVoltage:F1}V");
                            }
                            else
                            {
                                Console.WriteLine($"WARN: {targetVoltage:F1}V (invalid response)");
                            }
                        }
                        catch (TimeoutException)
                        {
                            // No response is OK for fast mode - command was sent
                            Console.WriteLine($"OK: {targetVoltage:F1}V (no ack)");
                        }
                    }
                    else
                    {
                        // Interactive mode - full operation with verification
                        var voltageSetter = new VoltageSetter(config, rs485, protocol);

                        Console.WriteLine("\nSetting voltage...");
                        Console.WriteLine("Press Ctrl+C to abort\n");

                        await voltageSetter.SetVoltageAsync(targetVoltage);

                        Console.WriteLine("\nOperation complete!");
                        Console.WriteLine("Press any key to exit...");
                        Console.ReadKey();
                    }
                }
                catch (UnauthorizedAccessException)
                {
                    Console.WriteLine($"ERROR: Cannot access {config.ComPort}");
                    Environment.Exit(1);
                }
                catch (IOException ex)
                {
                    Console.WriteLine($"ERROR: {ex.Message}");
                    Environment.Exit(1);
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"ERROR: {ex.Message}");
                    Environment.Exit(1);
                }
            }
        }

        static async Task RunDiagnosticMode()
        {
            Console.WriteLine("=== DIAGNOSTIC MODE ===\n");

            Console.Write("Enter COM port (e.g., COM3): ");
            string comPort = Console.ReadLine()?.ToUpper() ?? "COM3";

            Console.Write("Enter Device ID to test (1-6): ");
            byte deviceId = 1;
            if (byte.TryParse(Console.ReadLine(), out byte inputId))
            {
                deviceId = inputId;
            }

            var config = new Configuration
            {
                ComPort = comPort,
                DeviceId = deviceId,
                BaudRate = 9600,
                ReadTimeout = 2000
            };

            using (var rs485 = new RS485Controller(config))
            {
                try
                {
                    rs485.Open();
                    await Task.Delay(200);

                    var protocol = new QDQA01Protocol(config.DeviceId);

                    Console.WriteLine("\n========================================");
                    Console.WriteLine("QDQ-A01 COMMUNICATION DIAGNOSTICS");
                    Console.WriteLine("========================================\n");

                    Console.WriteLine("Configuration:");
                    Console.WriteLine($"  Port: {config.ComPort}");
                    Console.WriteLine($"  Baud Rate: {config.BaudRate}");
                    Console.WriteLine($"  Device ID: 0x{config.DeviceId:X2}");
                    Console.WriteLine();

                    // Test 1: Read current voltage
                    Console.WriteLine("Test 1: Read Current Voltage");
                    try
                    {
                        byte[] command = protocol.BuildReadVoltageCommand();
                        Console.WriteLine($"  TX: {BitConverter.ToString(command)}");
                        rs485.SendCommand(command);

                        byte[] response = rs485.ReadResponse(8, 1000);
                        Console.WriteLine($"  RX: {BitConverter.ToString(response)}");

                        if (protocol.ValidateResponse(response))
                        {
                            double voltage = protocol.ParseVoltageResponse(response);
                            Console.WriteLine($"  ✓ Current voltage: {voltage:F2}V");
                        }
                        else
                        {
                            Console.WriteLine("  ✗ Invalid response");
                        }
                    }
                    catch (TimeoutException)
                    {
                        Console.WriteLine("  ✗ Timeout - No response");
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"  ✗ Error: {ex.Message}");
                    }

                    await Task.Delay(200);

                    // Test 2: Try setting a test voltage (10V)
                    Console.WriteLine("\nTest 2: Set Voltage to 10V");
                    try
                    {
                        byte[] command = protocol.BuildSetVoltageCommand(10.0);
                        Console.WriteLine($"  TX: {BitConverter.ToString(command)}");
                        rs485.SendCommand(command);

                        byte[] response = rs485.ReadResponse(8, 1000);
                        Console.WriteLine($"  RX: {BitConverter.ToString(response)}");

                        if (protocol.ValidateResponse(response))
                        {
                            Console.WriteLine("  ✓ Set voltage successful");
                        }
                        else
                        {
                            Console.WriteLine("  ✗ Invalid response");
                        }
                    }
                    catch (TimeoutException)
                    {
                        Console.WriteLine("  ✗ Timeout - No response");
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"  ✗ Error: {ex.Message}");
                    }

                    await Task.Delay(500);

                    // Test 3: Verify the voltage changed
                    Console.WriteLine("\nTest 3: Verify Voltage Changed");
                    try
                    {
                        byte[] command = protocol.BuildReadVoltageCommand();
                        Console.WriteLine($"  TX: {BitConverter.ToString(command)}");
                        rs485.SendCommand(command);

                        byte[] response = rs485.ReadResponse(8, 1000);
                        Console.WriteLine($"  RX: {BitConverter.ToString(response)}");

                        if (protocol.ValidateResponse(response))
                        {
                            double voltage = protocol.ParseVoltageResponse(response);
                            Console.WriteLine($"  ✓ Current voltage: {voltage:F2}V");
                        }
                        else
                        {
                            Console.WriteLine("  ✗ Invalid response");
                        }
                    }
                    catch (TimeoutException)
                    {
                        Console.WriteLine("  ✗ Timeout - No response");
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"  ✗ Error: {ex.Message}");
                    }

                    Console.WriteLine("\n========================================");
                    Console.WriteLine("DIAGNOSTICS COMPLETE");
                    Console.WriteLine("========================================\n");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"\n✗ ERROR: {ex.Message}");
                }
            }

            Console.WriteLine("Press any key to exit...");
            Console.ReadKey();
        }

        static Configuration? ParseCommandLineArguments(string[] args)
        {
            var config = new Configuration();

            if (args.Length >= 2)
            {
                // Parse COM port
                config.ComPort = args[0].ToUpper();
                if (!config.ComPort.StartsWith("COM"))
                {
                    Console.WriteLine($"Error: Invalid COM port format: {args[0]}");
                    Console.WriteLine("Expected format: COM3, COM4, etc.");
                    return null;
                }

                // Parse Device ID
                if (!byte.TryParse(args[1], out byte deviceId))
                {
                    Console.WriteLine($"Error: Invalid Device ID: {args[1]}");
                    return null;
                }
                config.DeviceId = deviceId;

                return config;
            }
            else if (args.Length == 0)
            {
                // Interactive mode - prompt for values
                Console.Write("Enter COM port (e.g., COM3): ");
                string comPort = Console.ReadLine()?.ToUpper() ?? "COM3";
                config.ComPort = comPort;

                Console.Write("Enter Device ID (1-6): ");
                if (byte.TryParse(Console.ReadLine(), out byte deviceId))
                {
                    config.DeviceId = deviceId;
                }
                else
                {
                    Console.WriteLine("Invalid Device ID, using default: 1");
                    config.DeviceId = 1;
                }

                return config;
            }
            else
            {
                Console.WriteLine("Error: Insufficient arguments provided");
                return null;
            }
        }

        static void PrintUsage()
        {
            Console.WriteLine("\n╔════════════════════════════════════════════════════════════╗");
            Console.WriteLine("║              SETCOM-QDQ USAGE GUIDE (QDQ-A01)              ║");
            Console.WriteLine("╠════════════════════════════════════════════════════════════╣");
            Console.WriteLine("║ DIAGNOSTIC MODE:                                           ║");
            Console.WriteLine("║   setcom-qdq test              Run diagnostics             ║");
            Console.WriteLine("║                                                            ║");
            Console.WriteLine("║ VOLTAGE CONTROL:                                           ║");
            Console.WriteLine("║   setcom-qdq <PORT> <ID> <VOLTAGE>                         ║");
            Console.WriteLine("║                                                            ║");
            Console.WriteLine("║ PARAMETERS:                                                ║");
            Console.WriteLine("║   PORT    - COM port (e.g., COM3, COM5)                    ║");
            Console.WriteLine("║   ID      - Device ID on RS-485 bus (1-6)                  ║");
            Console.WriteLine("║   VOLTAGE - Target voltage in volts                        ║");
            Console.WriteLine("║                                                            ║");
            Console.WriteLine("║ EXAMPLES:                                                  ║");
            Console.WriteLine("║   setcom-qdq test                                          ║");
            Console.WriteLine("║   setcom-qdq COM5 1 30.5       Set to 30.5V                ║");
            Console.WriteLine("║   setcom-qdq COM5 2 50.0       Set to 50.0V                ║");
            Console.WriteLine("║   setcom-qdq COM5 1 0.0        Set to 0V (turn off)        ║");
            Console.WriteLine("║                                                            ║");
            Console.WriteLine("║ DEVICE INFO:                                               ║");
            Console.WriteLine("║   QDQ-A01 uses custom Modbus protocol                      ║");
            Console.WriteLine("║   Default settings: 9600 baud, 8N1, no flow control        ║");
            Console.WriteLine("║   Maximum voltage: 60V                                     ║");
            Console.WriteLine("║   Voltage is set immediately to target value               ║");
            Console.WriteLine("╚════════════════════════════════════════════════════════════╝");
            Console.WriteLine("\nRun without arguments for interactive mode.");
        }
    }
}
