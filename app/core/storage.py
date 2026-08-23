# Where measurements live on the Pi and on the USB flash drive.
#
# One surveyed point is one recording: a raw file and a metadata file sharing
# the same name. Measuring the same point again keeps both, the newer one gets
# a counter appended.
import os
import re
import shutil
import unicodedata

from app.core import config

RAW_SUFFIX = ".ubx"
META_SUFFIX = ".json"

# Anything else in a name would either break the path or escape the data folder
UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(name: str) -> str:
    """Turns user input into something safe to use as a file name.

    Parameters:
        name (string): Point id as it came from the request

    Returns:
        str: The cleaned name, empty when nothing usable is left
    """
    if not name:
        return ""

    # Czech names keep their meaning this way, mereni instead of m__en_
    stripped = unicodedata.normalize("NFKD", name.strip())
    stripped = stripped.encode("ascii", "ignore").decode("ascii")

    cleaned = UNSAFE_CHARS.sub("_", stripped)

    # Leading dots would hide the file or point at the parent directory
    return cleaned.strip("._")


def get_data_path() -> str:
    """The folder measurements are written to, created when missing."""
    base_path = config.LOCAL_DATA_PATH

    if not os.path.exists(base_path):
        os.makedirs(base_path)

    return base_path


def unique_name(base_name: str) -> str:
    """First free name for a point, counting up until one is unused.

    A second measurement of B1 becomes B1_1, a third B1_2, and so on.

    Parameters:
        base_name (string): Already cleaned point name

    Returns:
        str: Name without a suffix, free for both the raw and the metadata file
    """
    folder = get_data_path()

    if not os.path.exists(os.path.join(folder, base_name + RAW_SUFFIX)):
        return base_name

    counter = 1
    while True:
        candidate = f"{base_name}_{counter}"
        if not os.path.exists(os.path.join(folder, candidate + RAW_SUFFIX)):
            return candidate
        counter += 1


def get_points():
    """Lists the recorded points.

    Returns:
        list: Point names without the suffix, or False when unreadable
    """
    folder = config.LOCAL_DATA_PATH

    if not os.path.exists(folder):
        return []

    try:
        files = os.listdir(folder)
    except Exception as e:
        print(f"Directory list failed: {e}")
        return False

    return sorted(name[:-len(RAW_SUFFIX)] for name in files if name.endswith(RAW_SUFFIX))


def get_point_files(point_name):
    """Files belonging to one point, raw and metadata.

    Returns:
        list: Existing file names

        2: no such point
    """
    name = safe_name(point_name)
    folder = config.LOCAL_DATA_PATH

    files = [name + RAW_SUFFIX, name + META_SUFFIX]
    existing = [f for f in files if os.path.exists(os.path.join(folder, f))]

    if not existing:
        return 2

    return existing


def delete_point(point_name):
    """Removes one recording from local storage.

    Returns:
        True on success, 2 no such point, 3 delete failed
    """
    files = get_point_files(point_name)

    if files == 2:
        return 2

    folder = config.LOCAL_DATA_PATH

    for name in files:
        try:
            os.remove(os.path.join(folder, name))
        except Exception as e:
            print(f"Delete failed: {e}")
            return 3

    return True


def download_point(point_name, cleanup=False):
    """Copies one recording onto the USB flash drive.

    Parameters:
        point_name (string): Point name without the suffix
        cleanup (bool): Delete the local copy after a successful transfer

    Returns:
        True on success, 2 no such point or USB unavailable, 3 copy failed,
        4 cleanup failed
    """
    files = get_point_files(point_name)

    if files == 2:
        return 2

    usb_path = get_usb_path()

    if not usb_path:
        return 2

    folder = config.LOCAL_DATA_PATH

    try:
        for name in files:
            shutil.copy2(os.path.join(folder, name), os.path.join(usb_path, name))
    except Exception as e:
        print(f"Copy failed: {e}")
        return 3

    if cleanup:
        for name in files:
            try:
                os.remove(os.path.join(folder, name))
            except Exception as e:
                print(f"Cleanup failed: {e}")
                return 4

    return True


def get_usb_path():
    """Folder on the first mounted flash drive.

    Returns:
        str: The path, or False when no drive is mounted
    """
    base_path = config.BASE_USB_PATH

    try:
        devices = os.listdir(base_path)
    except FileNotFoundError:
        return False

    print(f"Found devices: {devices}")

    if not devices:
        return False

    return os.path.join(base_path, devices[0])
