"""
polly

driftmeasurement

PeakDrift objects are used to track (and optionally fit) the drift of a singl etalon
peak over time, from a series of mask files (saved outputs from polly.etalonanalysis).

GroupDrift objects contain a list of arbitrary PeakDrift objects within them. These
drifts can be then fit as a group (the group for instance binning the data in
wavelength, or across several orderlets).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property, partial
from operator import attrgetter
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from astropy import units as u
from matplotlib import pyplot as plt
from scipy.optimize import curve_fit

if TYPE_CHECKING:
    from collections.abc import Callable
    from numpy.typing import ArrayLike
    from astropy.units import Quantity

try:
    from polly.misc import savitzky_golay
    from polly.parsing import parse_filename, parse_yyyymmdd
    from polly.plotting import plot_style
except ImportError:
    from misc import savitzky_golay
    from parsing import parse_filename, parse_yyyymmdd
    from plotting import plot_style
plt.style.use(plot_style)


@dataclass
class PeakDrift:
    reference_mask: str  # Filename of the reference mask
    reference_wavelength: float  # Starting wavelength of the single peak
    local_spacing: float  # Local distance between wavelengths in reference mask

    masks: list[str]  # List of filenames to search
    dates: list[datetime] = field(default=None)

    # After initialisation, the single peak will be tracked as it appears in
    # each successive mask. The corresponding wavelengths at which it is found
    # will populate the `wavelengths` list.
    wavelengths: list[float | None] = field(default_factory=list)
    sigmas: list[float] = field(default_factory=list)
    valid: ArrayLike = field(default=None)

    auto_fit: bool = True

    fit: Callable = field(default=None)
    fit_err: list[float] = field(default=None)
    fit_slope: Quantity = field(default=None)
    fit_slope_err: Quantity = field(default=None)

    drift_file: str | Path = field(default=None)
    force_recalculate: bool = False
    recalculated: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.drift_file, str):
            self.drift_file = Path(self.drift_file)

        if self.drift_file.exists():
            # print(f"File exists for λ={self.reference_wavelength:.2f}")

            # First check if there is an existing file. If so, check its length.
            # If this is within 10% of the length of self.masks, don't recalculate
            # unless self.force_recalculate == True?

            if self.force_recalculate:
                # Then proceed as normal, track the drift from the masks
                self.track_drift()

            else:
                self.load_from_file()

        else:
            # No file exists, proceed as normal
            self.track_drift()

        if self.auto_fit:
            self.linear_fit()

    def load_from_file(self) -> None:
        # Then load all the information from the file
        # print(f"Loading drifts from file: {self.drift_file}")
        file_dates, file_wls, file_sigmas = np.transpose(np.loadtxt(self.drift_file))

        file_dates = [parse_yyyymmdd(d) for d in file_dates]

        self.dates = np.array(file_dates)
        self.wavelengths = np.array(file_wls)
        self.sigmas = np.array(file_sigmas)
        self.sigmas[self.sigmas == 0] = np.nan

        nanwavelength = np.where(~np.isnan(self.wavelengths), True, False)
        nansigma = np.where(~np.isnan(self.sigmas), True, False)
        self.valid = np.logical_and(nanwavelength, nansigma)

        if sum(self.valid) <= 3:  # noqa: PLR2004
            print(
                "Too few located peaks for λ="
                + f"{self.reference_wavelength:.2f} ({len(self.valid)})"
            )

    @cached_property
    def valid_wavelengths(self) -> list[float]:
        if self.valid is None:
            return self.wavelengths

        return list(np.array(self.wavelengths)[self.valid])

    @cached_property
    def valid_sigmas(self) -> list[float]:
        if self.valid is None:
            return self.sigmas

        return list(np.array(self.sigmas)[self.valid])

    @cached_property
    def valid_dates(self) -> list[datetime]:
        if self.valid is None:
            return self.dates

        return list(np.array(self.dates)[self.valid])

    @cached_property
    def reference_date(self) -> datetime:
        return parse_filename(self.reference_mask).date

    @cached_property
    def days_since_reference_date(self) -> list[float]:
        return [(d - self.reference_date).days for d in self.valid_dates]

    @cached_property
    def timesofday(self) -> list[str]:
        if self.valid is None:
            valid_masks = self.masks

        else:
            valid_masks = list(np.array(self.masks)[self.valid])

        return [parse_filename(m).timeofday for m in valid_masks]

    @cached_property
    def smoothed_wavelengths(self) -> list[float]:
        return savitzky_golay(y=self.valid_wavelengths, window_size=21, order=3)

    @cached_property
    def deltas(self) -> list[float]:
        return self.valid_wavelengths - self.reference_wavelength

    def get_delta_at_date(
        self,
        date: datetime | list[datetime],
    ) -> float | list[float]:
        """
        Returns the delta value for a given date. If there is no data for a given date,
        returns NaN.

        If more than one matching date is present (why?), it returns the delta value for
        the first occurrance of the date.
        """

        if isinstance(date, list):
            return [self.get_delta_at_date(date=d) for d in date]

        assert isinstance(date, datetime)

        for i, d in enumerate(self.valid_dates):
            if d == date:
                return self.deltas[i]
        return np.nan

    @cached_property
    def fractional_deltas(self) -> list[float]:
        return self.deltas / self.reference_wavelength

    def get_fractional_delta_at_date(
        self,
        date: datetime | list[datetime],
    ) -> float | list[float]:
        return self.get_delta_at_date(date) / self.reference_wavelength

    @cached_property
    def smoothed_deltas(self) -> list[float]:
        return savitzky_golay(y=self.deltas, window_size=21, order=3)

    def track_drift(self) -> PeakDrift:
        """
        Starting with the reference wavelength, track the position of the matching peak
        in successive masks. This function uses the last successfully found peak
        wavelength as the centre of the next search window, so can track positions even
        if they greatly exceed any reasonable search window over time.
        """

        print(f"Tracking drift for λ={self.reference_wavelength:.2f}...")

        self.dates = []

        last_wavelength: float = None

        for m in self.masks:
            self.dates.append(parse_filename(m).date)
            peaks, sigmas = np.transpose(np.loadtxt(m))

            if last_wavelength is None:
                # First mask
                last_wavelength = self.reference_wavelength

            try:  # Find the closest peak in the mask
                closest_index = np.nanargmin(np.abs(peaks - last_wavelength))
            except ValueError:  # What would give us a ValueError here?
                self.wavelengths.append(None)
                self.sigmas.append(None)
                continue

            wavelength = peaks[closest_index]
            sigma = sigmas[closest_index]

            # Check if the new peak is within a search window around the last
            if abs(last_wavelength - wavelength) <= self.local_spacing / 50:
                self.wavelengths.append(wavelength)
                last_wavelength = wavelength
                self.sigmas.append(sigma)
            else:  # No peak found within the window!
                self.wavelengths.append(None)
                self.sigmas.append(None)
                # Don't update last_wavelength: we will keep searching at the
                # same wavelength as previously.

        # Assign self.valid as a mask where wavelengths were successfully found
        self.valid = np.where(self.wavelengths, True, False)
        self.recalculated = True

        return self

    def linear_fit(
        self,
        fit_fractional: bool = False,
    ) -> PeakDrift:
        """
        - Fit the tracked drift with a linear function
        - Assign self.fit with a Callable function
        - Assign self.fit_slope with the slope of that function in relevant units.
          picometers per day? Millimetres per second radial velocity per day?
        """

        if len(self.valid_wavelengths) == 0:
            print(f"No valid wavelengths found for {self.reference_wavelength}")
            print("Running PeakDrift.track_drift() first.")
            self.track_drift()

        deltas_to_use = self.fractional_deltas if fit_fractional else self.deltas

        def linear_model(
            x: float | list[float], slope: float
        ) -> float | ArrayLike[float]:
            if isinstance(x, list):
                x = np.array(x)

            return slope * x

        try:
            p, cov = curve_fit(
                f=linear_model,
                xdata=self.days_since_reference_date,
                ydata=deltas_to_use,
                sigma=self.valid_sigmas,
                p0=[0],
                absolute_sigma=True,
            )

            self.fit = partial(linear_model, slope=p[0])
            self.fit_err = np.sqrt(cov)
            self.fit_slope = p[0] / u.day
            self.fit_slope_err = np.sqrt(cov[0][0]) / u.day

        except (ValueError, RuntimeError):
            self.fit = lambda x: np.nan  # noqa: ARG005
            self.fit_err = np.nan
            self.fit_slope = np.nan / u.day
            self.fit_slope_err = np.nan / u.day

        return self

    def fit_residuals(self, fractional: bool = False) -> list[float]:
        if fractional:
            return (
                self.fractional_deltas - self.fit(self.days_since_reference_date).value
            )

        return self.deltas - self.fit(self.days_since_reference_date).value

    def save_to_file(self, path: str | Path | None = None) -> PeakDrift:
        """ """

        if not path:
            if self.drift_file:
                path = self.drift_file
            else:
                raise Exception("No file path passed in and no drift_file specified")

        if isinstance(path, str):
            path = Path(path)

        if path.is_dir():
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists() and not self.recalculated:
            # Then don't need to save the file again
            return self

        datestrings = [f"{d:%Y%m%d}" for d in self.valid_dates]
        wlstrings = [f"{wl}" for wl in self.valid_wavelengths]
        sigmastrings = [f"{wl}" for wl in self.valid_sigmas]

        try:
            np.savetxt(
                f"{path}",
                np.transpose([datestrings, wlstrings, sigmastrings]),
                fmt="%s",
            )
        except FileExistsError:
            # print(e)
            ...

        return self


@dataclass
class GroupDrift:
    """
    A class that tracks the drift of a group of peaks and fits their slope
    together. Rather than computing the drift (and fitting a linear slope) for
    individual peaks, here we can consider a block of wavelengths all together.
    """

    peakDrifts: list[PeakDrift]

    group_fit: Callable = field(default=None)
    group_fit_err: list[float] = field(default=None)
    group_fit_slope: float = field(default=None)
    group_fit_slope_err: float = field(default=None)

    def __post_init__(self) -> None:
        self.peakDrifts = sorted(
            self.peakDrifts, key=attrgetter("reference_wavelength")
        )

    @cached_property
    def mean_wavelength(self) -> float:
        return np.mean([pd.reference_wavelength for pd in self.peakDrifts])

    @cached_property
    def min_wavelength(self) -> float:
        return min(self.peakDrifts[0].reference_wavelength)

    @cached_property
    def max_wavelength(self) -> float:
        return max(self.peakDrifts[-1].reference_wavelength)

    @property
    def all_dates(self) -> list[datetime]:
        all_dates = []

        for pd in self.peakDrifts:
            all_dates.extend(pd.valid_dates)

        return all_dates

    @cached_property
    def reference_date(self) -> datetime:
        return min(self.all_dates)

    @cached_property
    def all_days_since_reference_date(self) -> list[float]:
        return [(d - self.reference_date).days for d in self.all_dates]

    @cached_property
    def unique_dates(self) -> list[datetime]:
        return sorted(set(self.all_dates))

    @cached_property
    def all_deltas(self) -> list[float]:
        all_deltas = []

        for pd in self.peakDrifts:
            all_deltas.extend(pd.fractional_deltas)

        return all_deltas

    @cached_property
    def all_sigmas(self) -> list[float]:
        all_sigmas = []

        for pd in self.peakDrifts:
            all_sigmas.extend(pd.valid_sigmas)

        return all_sigmas

    @cached_property
    def all_relative_sigmas(self) -> list[float]:
        all_relative_sigmas = []

        for pd in self.peakDrifts:
            all_relative_sigmas.extend(pd.valid_sigmas / pd.reference_wavelength)

        return all_relative_sigmas

    @property
    def mean_deltas(self) -> list[float]:
        all_deltas = [pd.deltas for pd in self.peakDrifts]
        return list(np.mean(all_deltas, axis=1))

    def fit_group_drift(self, verbose: bool = False) -> None:
        if verbose:
            print(f"{self.all_days_since_reference_date}")
            print(f"{self.all_deltas}")

        def linear_model(
            x: float | list[float], slope: float
        ) -> float | ArrayLike[float]:
            if isinstance(x, list):
                x = np.array(x)

            return slope * x

        try:
            p, cov = curve_fit(
                f=linear_model,
                xdata=self.all_days_since_reference_date,
                ydata=self.all_deltas,
                sigma=self.all_relative_sigmas,
                p0=[0],
                absolute_sigma=True,
            )

            self.group_fit = partial(linear_model, slope=p[0])
            self.group_fit_err = np.sqrt(cov)
            self.group_fit_slope = p[0]
            self.group_fit_slope_err = np.sqrt(cov[0][0])

        except Exception as e:
            print(e)
            self.group_fit = None
            self.group_fit_err = None
            self.group_fit_slope = None
            self.group_fit_slope_err = None
