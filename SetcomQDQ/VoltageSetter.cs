using System;
using System.Threading.Tasks;
using SetcomCore;

namespace SetcomQDQ
{
    public class VoltageSetter
    {
        private readonly Configuration _config;
        private readonly RS485Controller _rs485;
        private readonly QDQA01Protocol _protocol;

        public VoltageSetter(Configuration config, RS485Controller rs485, QDQA01Protocol protocol)
        {
            _config = config;
            _rs485 = rs485;
            _protocol = protocol;
        }

        public async Task SetVoltageAsync(double targetVoltage)
        {
            if (targetVoltage > _config.MaxVoltage)
            {
                throw new ArgumentException($"Target voltage {targetVoltage}V exceeds maximum {_config.MaxVoltage}V");
            }

            if (targetVoltage < 0)
            {
                throw new ArgumentException($"Target voltage cannot be negative");
            }

            // Step 1: Enable output if not already enabled
            Console.WriteLine("Enabling output...");
            try
            {
                byte[] enableCmd = _protocol.BuildEnableOutputCommand(true);
                _rs485.SendCommand(enableCmd);
                await Task.Delay(100);

                byte[] enableResponse = _rs485.ReadResponse(7, 500);
                if (_protocol.ValidateResponse(enableResponse))
                {
                    Console.WriteLine("Output enabled");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Warning: Could not verify output enable - {ex.Message}");
            }

            await Task.Delay(200);

            // Step 2: Set voltage
            Console.WriteLine($"\nSetting voltage:");
            Console.WriteLine($"  Device ID: {_config.DeviceId}");
            Console.WriteLine($"  Target: {targetVoltage:F2}V");
            Console.WriteLine($"  Protocol: Modbus RTU @ {_config.BaudRate} baud\n");

            try
            {
                // Send voltage command
                byte[] command = _protocol.BuildSetVoltageCommand(targetVoltage);
                _rs485.SendCommand(command);

                // Wait for response (expected 8 bytes for write command)
                byte[] response = _rs485.ReadResponse(8, 500);

                if (_protocol.ValidateResponse(response))
                {
                    if (_protocol.IsErrorResponse(response))
                    {
                        Console.WriteLine($"✗ Device returned error for {targetVoltage:F2}V");
                        throw new Exception("Device reported an error");
                    }
                    else
                    {
                        Console.WriteLine($"✓ Voltage set to {targetVoltage:F2}V");
                    }
                }
                else
                {
                    Console.WriteLine($"✗ Invalid CRC in response");
                    throw new Exception("Invalid response from device");
                }
            }
            catch (TimeoutException)
            {
                Console.WriteLine($"✗ No response from device");
                throw;
            }

            // Step 3: Verify voltage
            await Task.Delay(500);
            Console.WriteLine("\nVerifying voltage...");
            try
            {
                byte[] readCmd = _protocol.BuildReadVoltageCommand();
                _rs485.SendCommand(readCmd);

                byte[] readResponse = _rs485.ReadResponse(8, 500);
                if (_protocol.ValidateResponse(readResponse))
                {
                    double actualVoltage = _protocol.ParseVoltageResponse(readResponse);
                    Console.WriteLine($"Actual voltage reading: {actualVoltage:F2}V");

                    // Check if voltage is close to target (within 0.5V tolerance)
                    if (Math.Abs(actualVoltage - targetVoltage) > 0.5)
                    {
                        Console.WriteLine($"⚠ Warning: Voltage mismatch (expected {targetVoltage:F2}V, got {actualVoltage:F2}V)");
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"Could not verify voltage: {ex.Message}");
            }
        }
    }
}
