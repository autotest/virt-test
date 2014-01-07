/*
 * Eject removable drive tool in windows, works like a simple  eject tool
 * in linux;
 * For cdrom test, used to lock/unlock, eject/close cdrom in windows platform;
 *
 * Tested on win7 64bit OS and compile it with dev c++;
 *
 */

#include <windows.h>
#include <winioctl.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <getopt.h>
#include <string.h>

void usage(int ret)
{
    printf("eject removable media\n");
    printf("eject [-t] [-i off|on|1|0] x:\n");
    printf("\t: -t: close cdrom\n");
    printf("\t: -i on|off|1|0: close cdrom\n");
    printf("\t: x: cdrom drive letter eg, E:");
    exit(ret);
}

static DWORD get_drive_type(WCHAR drive)
{
    static const WCHAR rootW[] = {'a',':','\\',0};
    WCHAR path[16];
    memcpy( path, rootW, sizeof(rootW));
    path[0] = drive;
    return GetDriveTypeW(path);
}

static BOOL cdrom_io_control(HANDLE handle, DWORD command, void *pr)
{
    DWORD result;
    DWORD buffer_size = 0;

    if(pr != NULL) buffer_size = sizeof(pr);
    if(!DeviceIoControl(handle, command, pr, buffer_size, NULL, 0,
                        &result, NULL))
    {
        printf("%s failed with err %d", command, GetLastError());
        exit(GetLastError());
    }

    return TRUE;
}

static HANDLE get_handler(WCHAR drive)
{
    static const WCHAR deviceW[] = {'\\', '\\', '.', '\\', 'a', ':', 0};
    WCHAR buffer[16];
    HANDLE handle;

    if (get_drive_type(drive) != DRIVE_CDROM)
    {
        printf("Drive %c: is not a CD or is not mounted\n", (char)drive);
        exit(1);
    }
    memcpy(buffer, deviceW, sizeof(deviceW));
    buffer[4] = drive;
    handle = CreateFileW(buffer, GENERIC_WRITE | GENERIC_READ,
                         FILE_SHARE_READ|FILE_SHARE_WRITE, NULL,
                         OPEN_EXISTING, 0, 0 );
    if (handle == INVALID_HANDLE_VALUE)
    {
        printf("Cannot get_handler device for drive %c:\n", (char)drive);
        exit(1);
    }
    cdrom_io_control(handle, FSCTL_LOCK_VOLUME, NULL);

    return handle;
 }

static BOOL close_handler(HANDLE handle)
{
    BOOL ret;
    ret = cdrom_io_control(handle, FSCTL_UNLOCK_VOLUME, NULL);
    CloseHandle(handle);
    return ret;
}

static BOOL eject_cdrom(WCHAR drive)
{
    HANDLE handle;
    PREVENT_MEDIA_REMOVAL removal;
    removal.PreventMediaRemoval = FALSE;

    handle = get_handler(drive);
    cdrom_io_control(handle, FSCTL_DISMOUNT_VOLUME, NULL);
    cdrom_io_control(handle, IOCTL_STORAGE_MEDIA_REMOVAL, &removal);
    cdrom_io_control(handle, IOCTL_STORAGE_EJECT_MEDIA, NULL);
    close_handler(handle);

    return TRUE;
}

static BOOL close_cdrom(WCHAR drive)
{
    HANDLE handle;
    BOOL ret;

    handle = get_handler(drive);
    ret = cdrom_io_control(handle, IOCTL_STORAGE_LOAD_MEDIA, NULL);
    close_handler(handle);

    return ret;
}

static BOOL lock_cdrom(WCHAR drive)
{
    HANDLE handle;
    PREVENT_MEDIA_REMOVAL removal;
    removal.PreventMediaRemoval = TRUE;

    handle = get_handler(drive);
    cdrom_io_control(handle, IOCTL_STORAGE_MEDIA_REMOVAL, &removal);
    close_handler(handle);

    return TRUE;
}

static BOOL unlock_cdrom(WCHAR drive)
{
    HANDLE handle;
    PREVENT_MEDIA_REMOVAL removal;
    removal.PreventMediaRemoval = FALSE;

    handle = get_handler(drive);
    cdrom_io_control(handle, IOCTL_STORAGE_MEDIA_REMOVAL, &removal);
    close_handler(handle);

    return TRUE;
}

int main(int argc, char *argv[])
{
    int ch;
    opterr = 0;
    if (argc < 2) usage(1);
    DWORD drive = argv[argc - 1][0];
    while((ch = getopt(argc, argv, "hi:t")) != -1)
    {
        switch(ch)
        {
            case 'h':
                usage(0);
            case 'i':
                if (!strcmp(optarg, "on") || !strcmp(optarg, "1"))
                    lock_cdrom(drive) ? exit(0) : exit(1);
                if (!strcmp(optarg, "off") || !strcmp(optarg, "0"))
                    unlock_cdrom(drive) ? exit(0) : exit(1);
                usage(1);
            case 't':
                close_cdrom(drive) ? exit(0) : exit(1);
            default:
                usage(1);
        }
    }
    eject_cdrom(drive);

    return 0;
}
