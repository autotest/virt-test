using System;
using System.IO;
using System.IO.Ports;
using System.Threading;
using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;

public class PortChat
{
    static bool _continue;
    static SerialPort _serialPort;
    private static StringBuilder cmdOutput = null;
    private static StringBuilder cmdError = null;
    private static StreamWriter cmdStreamWriter;
    private static Process ps;
    private static string helloMsg;

    public static void Main()
    {
        string message;
        StringComparer stringComparer = StringComparer.OrdinalIgnoreCase;
        Thread readThread = new Thread(Read);

        // Create a new SerialPort object with default settings.
        _serialPort = new SerialPort();

        // Allow the user to set the appropriate properties.
        SetPort();
        
        _serialPort.Open();
        _continue = true;

        // Init the cmd process
        ps = new Process();

        ps.StartInfo.FileName = "cmd.exe";
        ps.StartInfo.UseShellExecute = false;
        ps.StartInfo.RedirectStandardInput = true;
        ps.StartInfo.RedirectStandardOutput = true;
        ps.StartInfo.RedirectStandardError = true;
        ps.StartInfo.CreateNoWindow = true;
        cmdOutput = new StringBuilder("");
        cmdError = new StringBuilder("");
        ps.OutputDataReceived += new DataReceivedEventHandler(cmdOutputHandler);
        ps.ErrorDataReceived += new DataReceivedEventHandler(cmdErrorHandler);
        Console.WriteLine("CMD process ready.");
        Console.WriteLine("Type QUIT to exit");

        readThread.Start();
        ps.Start();
        ps.BeginOutputReadLine();
        ps.BeginErrorReadLine();
        cmdStreamWriter = ps.StandardInput;

        // Get the hello message
        cmdStreamWriter.WriteLine();
        while (cmdOutput.Length == 0)
        {
            Thread.Sleep(5);
        }
        helloMsg = cmdOutput.ToString();
        Console.WriteLine(cmdOutput);
        cmdOutput.Remove(0,cmdOutput.Length);
        
        while (_continue)
        {
            message = Console.ReadLine();

            if (stringComparer.Equals("quit", message))
            {
                _continue = false;
            }
            else
            {
                _serialPort.WriteLine(message);
            }
        }

        readThread.Join();

        _serialPort.Close();
        Console.WriteLine("Serial port closed");
        cmdStreamWriter.Close();
        Console.WriteLine("Input stream closed");
        ps.WaitForExit();
        ps.Close();
        Console.WriteLine("Exit");

    }

    public static void Read()
    {
        while (_continue)
        {
            try
            {
                string message = _serialPort.ReadLine();
                if (message.Length == 0)
                {//Connection prompt message
                    _serialPort.WriteLine("Please wait...");
                    _serialPort.WriteLine(helloMsg);
                }
                else
                {
                    Console.WriteLine(message);
                    RunCmd(message);
                }
            }
            catch (TimeoutException) { }
        }
    }

    public static void RunCmd(string cmdline)
    {    

        cmdStreamWriter.WriteLine(cmdline);
        cmdStreamWriter.WriteLine();

        string regex = @"^\w:\\.*>*$";
        bool _wait = true;
        while (_wait)
        {
            if (cmdOutput.Length > 4)
            {
                if (!Regex.IsMatch(cmdOutput.ToString().Substring(4), regex.ToString(), RegexOptions.Multiline))
                {
                    Thread.Sleep(1000);
                }
                else
                {
                    _wait = false;
                }
            }
        }
        _serialPort.Write(String.Format("{0}", cmdOutput));
        if (cmdError.Length > 0)
        {
            _serialPort.Write(String.Format("{0}", cmdError));
        }

        //Clean up the output and error stream 
        cmdOutput.Remove(0, cmdOutput.Length);
        cmdError.Remove(0, cmdError.Length);
    }

    public static void SetPort()
    {
        string cfgPath = Directory.GetCurrentDirectory();
        cfgPath += "\\serialport.cfg";
        Console.WriteLine(cfgPath);
        if (File.Exists(cfgPath))
        {
            using (StreamReader sr = File.OpenText(cfgPath))
            {
                string s = "";
                while ((s = sr.ReadLine()) != null)
                {
                    Regex regex = new Regex("=");
                    string[] substrings = regex.Split(s);
                    Console.WriteLine("{0}:{1}", substrings[0], substrings[1]);
                    switch (substrings[0])
                    {
                        case "PortName":
                            _serialPort.PortName = substrings[1];
                            break;
                        case "BaudRate":
                            _serialPort.BaudRate = int.Parse(substrings[1]);
                            break;
                        case "Parity":
                            _serialPort.Parity = (Parity)Enum.Parse(typeof(Parity), substrings[1]);
                            break;
                        case "DataBits":
                            _serialPort.DataBits = int.Parse(substrings[1]);
                            break;
                        case "StopBits":
                            _serialPort.StopBits = (StopBits)Enum.Parse(typeof(StopBits), substrings[1]);
                            break;
                        case "Handshake":
                            _serialPort.Handshake = (Handshake)Enum.Parse(typeof(Handshake), substrings[1]);
                            break;
                        case "ReadTimeout":
                            _serialPort.ReadTimeout = int.Parse(substrings[1]);
                            break;
                        case "WriteTimeout":
                            _serialPort.WriteTimeout = int.Parse(substrings[1]);
                            break;
                    }
                }
            }
        }
    }

    private static void cmdOutputHandler(object sendingProcess,
        DataReceivedEventArgs outLine)
    {
        if (!String.IsNullOrEmpty(outLine.Data))
        {
            cmdOutput.Append(outLine.Data + "\r\n");
        }
    }

    private static void cmdErrorHandler(object sendingProcess,
    DataReceivedEventArgs outLine)
    {
        if (!String.IsNullOrEmpty(outLine.Data))
        {
            cmdError.Append(outLine.Data + "\r\n");
        }
    }
}
