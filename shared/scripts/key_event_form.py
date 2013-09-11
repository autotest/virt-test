import wx


class TestForm(wx.Frame):

    def __init__(self):
        wx.Frame.__init__(self, None, wx.ID_ANY, "Test")

        # Add a panel so it looks correct on all platforms
        panel = wx.Panel(self, wx.ID_ANY)
        btn = wx.TextCtrl(panel, value="")

        btn.Bind(wx.EVT_CHAR, self.on_char_event)
        btn.SetFocus()

        # Clean text file
        input_file = open("/tmp/autotest-rv_input", "w")
        input_file.write("")
        input_file.close()

    def on_char_event(self, event):
        keycode = event.GetKeyCode()

        # Store caught keycodes into text file
        input_file = open("/tmp/autotest-rv_input", "a")
        input_file.write("%s," % str(keycode))
        input_file.close()
        event.Skip()

if __name__ == "__main__":
    APP = wx.PySimpleApp()
    FRAME = TestForm()
    FRAME.Show()
    APP.MainLoop()
