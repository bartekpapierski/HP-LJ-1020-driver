// THROWAWAY PROTOTYPE: send an explicitly selected firmware or ZjStream file
// through PAPPL's USB device layer. This is not a production spooler.

#include <pappl/pappl.h>

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static void
device_error(const char *message, void *data)
{
  (void)data;
  fprintf(stderr, "PAPPL USB: %s\n", message);
}

int
main(int argc, char *argv[])
{
  unsigned char buffer[16384];
  pappl_device_t *device;
  ssize_t count;
  size_t total = 0;
  int input;

  if (argc != 3)
  {
    fprintf(stderr, "Usage: %s USB-URI INPUT-FILE\n", argv[0]);
    return 2;
  }

  if ((input = open(argv[2], O_RDONLY)) < 0)
  {
    fprintf(stderr, "%s: %s\n", argv[2], strerror(errno));
    return 1;
  }

  if ((device = papplDeviceOpen(argv[1], argv[2], device_error, NULL)) == NULL)
  {
    close(input);
    return 1;
  }

  while ((count = read(input, buffer, sizeof(buffer))) > 0)
  {
    ssize_t offset = 0;

    while (offset < count)
    {
      ssize_t written = papplDeviceWrite(device, buffer + offset,
                                         (size_t)(count - offset));
      if (written <= 0)
      {
        fputs("PAPPL USB write failed.\n", stderr);
        papplDeviceClose(device);
        close(input);
        return 1;
      }

      offset += written;
      total += (size_t)written;
    }
  }

  papplDeviceFlush(device);
  papplDeviceClose(device);
  close(input);

  if (count < 0)
  {
    fprintf(stderr, "%s: %s\n", argv[2], strerror(errno));
    return 1;
  }

  fprintf(stderr, "Sent %zu bytes through PAPPL USB.\n", total);
  return 0;
}
