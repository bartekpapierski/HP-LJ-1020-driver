// THROWAWAY PROTOTYPE: enumerate and claim the reference printer through
// PAPPL's public USB device API without transmitting firmware or print data.

#include <pappl/pappl.h>

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

typedef struct probe_state_s
{
  char uri[2048];
  bool found;
} probe_state_t;

static void
device_error(const char *message, void *data)
{
  (void)data;
  fprintf(stderr, "usb_probe_error=%s\n", message);
}

static bool
find_reference_printer(const char *device_info, const char *device_uri,
                       const char *device_id, void *data)
{
  probe_state_t *state = (probe_state_t *)data;

  if ((device_info && strstr(device_info, "LaserJet 1020")) ||
      (device_id && strstr(device_id, "LaserJet 1020")))
  {
    snprintf(state->uri, sizeof(state->uri), "%s", device_uri);
    state->found = true;
    return true;
  }

  return false;
}

int
main(void)
{
  char device_id[2048];
  pappl_device_t *device;
  probe_state_t state = { "", false };

  if (!papplDeviceList(PAPPL_DEVTYPE_USB, find_reference_printer, &state,
                       device_error, NULL) || !state.found)
  {
    fputs("usb_probe_result=reference-printer-not-found\n", stderr);
    return 1;
  }

  if ((device = papplDeviceOpen(state.uri, "lifecycle-access-probe",
                                device_error, NULL)) == NULL)
  {
    fputs("usb_probe_result=claim-failed\n", stderr);
    return 1;
  }

  device_id[0] = '\0';
  papplDeviceGetID(device, device_id, sizeof(device_id));
  papplDeviceClose(device);

  puts("usb_probe_result=claimed");
  puts("usb_probe_model=HP-LaserJet-1020");
  printf("usb_probe_firmware_identity=%s\n",
         strstr(device_id, "FWVER:") ? "present" : "absent");
  return 0;
}
