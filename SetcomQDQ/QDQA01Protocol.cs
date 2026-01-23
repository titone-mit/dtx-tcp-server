using System;
using SetcomCore;

namespace SetcomQDQ
{
    /// <summary>
    /// Protocol handler for QDQ-A01 transformer
    /// Uses custom Modbus variant with Function Code 0x10 (Write Multiple Registers)
    /// and 8-bit register addressing
    /// </summary>
    public class QDQA01Protocol
    {
        private readonly byte _deviceAddress;

        public QDQA01Protocol(byte deviceAddress = 0x01)
        {
            _deviceAddress = deviceAddress;
        }

        /// <summary>
        /// Build command to set working voltage
        /// Register 0x15-0x16 holds the working voltage (low byte, high byte)
        /// Voltage is stored as value * 10 (e.g., 450 = 45.0V)
        /// </summary>
        public byte[] BuildSetVoltageCommand(double voltage)
        {
            // Convert voltage to device units (multiply by 10)
            ushort voltageValue = (ushort)(voltage * 10);

            // Split into low and high bytes
            byte voltageLow = (byte)(voltageValue & 0xFF);
            byte voltageHigh = (byte)(voltageValue >> 8);

            // Command: 0x10 (Write Multiple Registers)
            // Register address: 0x15 (working voltage low byte)
            // Number of registers: 2 (low byte and high byte)
            byte[] command = new byte[8];
            command[0] = _deviceAddress;      // Slave address
            command[1] = 0x10;                // Command word: Write registers
            command[2] = 0x15;                // Register start address (0x15 = working voltage low)
            command[3] = 0x02;                // Number of registers (2 bytes for voltage)
            command[4] = voltageLow;          // Working voltage low byte
            command[5] = voltageHigh;         // Working voltage high byte

            ModbusHelper.AppendCRC16(command, 6);

            return command;
        }

        /// <summary>
        /// Build command to enable output
        /// Register 0x11: 0 = no output, non-zero = output
        /// </summary>
        public byte[] BuildEnableOutputCommand(bool enable)
        {
            byte[] command = new byte[7];
            command[0] = _deviceAddress;      // Slave address
            command[1] = 0x10;                // Command word: Write register
            command[2] = 0x11;                // Register address (output enable)
            command[3] = 0x01;                // Number of registers
            command[4] = enable ? (byte)0x01 : (byte)0x00;  // Value

            ModbusHelper.AppendCRC16(command, 5);

            return command;
        }

        /// <summary>
        /// Build command to read current working voltage
        /// </summary>
        public byte[] BuildReadVoltageCommand()
        {
            byte[] command = new byte[8];
            command[0] = _deviceAddress;      // Slave address
            command[1] = 0x03;                // Command word: Read registers
            command[2] = 0x15;                // Register start address (high byte = 0x00)
            command[3] = 0x02;                // Number of registers (2 for voltage)
            command[4] = 0x00;                // Padding
            command[5] = 0x00;                // Padding

            ModbusHelper.AppendCRC16(command, 4);

            // Resize to 6 bytes for read command
            Array.Resize(ref command, 6);

            return command;
        }

        /// <summary>
        /// Parse voltage from read response
        /// </summary>
        public double ParseVoltageResponse(byte[] response)
        {
            if (response.Length < 8)
                return -1;

            // Response format: [Addr][Cmd][StartReg][NumRegs][ValueLow][ValueHigh][CRC_L][CRC_H]
            byte voltageLow = response[4];
            byte voltageHigh = response[5];
            ushort voltageValue = (ushort)(voltageLow | (voltageHigh << 8));

            return voltageValue / 10.0;  // Convert back to volts
        }

        /// <summary>
        /// Validate response CRC
        /// </summary>
        public bool ValidateResponse(byte[] response)
        {
            if (response == null || response.Length < 3)
                return false;

            // Check if address matches
            if (response[0] != _deviceAddress)
                return false;

            return ModbusHelper.ValidateResponse(response);
        }

        /// <summary>
        /// Check if response indicates an error
        /// </summary>
        public bool IsErrorResponse(byte[] response)
        {
            if (response == null || response.Length < 2)
                return true;

            // Error responses have bit 7 set in the command byte
            return (response[1] & 0x80) != 0;
        }
    }
}
