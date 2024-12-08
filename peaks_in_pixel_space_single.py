#!/usr/bin/env python
"""
Single file analysis command-line utility that outputs a CSV with the pixel
location of identified and fit peaks.

Takes a single filename as argument.
"""

from __future__ import annotations

import logging
import argparse
from pathlib import Path

import numpy as np

from astropy.io import fits

from matplotlib import pyplot as plt

try:
    from polly.log import logger
    from polly.kpf import TIMESOFDAY
    from polly.parsing import parse_bool, parse_orderlets
    from polly.etalonanalysis import Spectrum
    from polly.plotStyle import plotStyle
except ImportError:
    from log import logger
    from kpf import TIMESOFDAY
    from parsing import parse_bool, parse_orderlets
    from etalonanalysis import Spectrum
    from plotStyle import plotStyle
plt.style.use(plotStyle)


DEFAULT_FILENAME = "/data/kpf/masters/"+\
    "20240515/kpf_20240515_master_arclamp_autocal-etalon-all-eve_L1.fits"


def main(
    filename: str,
    orderlets: str | list[str] | None,
    fit_plot: bool,
    ) -> None:
    
    if isinstance(orderlets, str):
        orderlets = [orderlets]
    
    Path(f"{OUTDIR}/masks/").mkdir(parents=True, exist_ok=True)   
    
    date = "".join(fits.getval(filename, "DATE-OBS").split("-"))
    timeofday = fits.getval(filename, "OBJECT").split("-")[-1]
    assert timeofday in TIMESOFDAY
        
    pp = f"{f'[{date} {timeofday:>5}]':<20}" # Print/logging line prefix

    print(filename)

    s = Spectrum(
        spec_file = filename,
        wls_file = None, # It will try to find the corresponding WLS file
        orderlets_to_load = orderlets,
        pp = pp,
        )
    s.locate_peaks()
    s.fit_peaks(space="pixel")
    
    
    # Now you can access peak locations with the following:
    center_pixels  = [p.center_pixel        for p in s.peaks()]
    pixel_std_devs = [p.center_pixel_stddev for p in s.peaks()]
    
    order_is, center_pixels, pixel_std_devs =\
        np.transpose(
            [
                (p.i, p.center_pixel, p.center_pixel_stddev)\
                    for p in s.peaks()
            ]
        )
    
    for i, pix, dpix in zip(order_is, center_pixels, pixel_std_devs):
        print(f"{pp}Order i={i:<3.0f}| {pix:.3f} +/- {dpix:.4f}")
    
    
    # And save the output to a CSV with built-in methods like so:        
    for ol in s.orderlets:
        try:
            s.save_peak_locations(
                filename = f"{OUTDIR}/masks/"+\
                    f"{date}_{timeofday}_{ol}_etalon_wavelengths.csv",
                orderlet = ol,
                space = "pixel",
                filtered = False,
                )
        except Exception as e:
            print(f"{pp}{e}")
            continue
            
        if fit_plot:
            Path(f"{OUTDIR}/fit_plots").mkdir(parents=True, exist_ok=True)
            for ol in s.orderlets:
                s.plot_peak_fits(orderlet=ol)
                plt.savefig(f"{OUTDIR}/fit_plots/"+\
                    f"{date}_{timeofday}_{ol}_etalon_fits.png")
                plt.close()


parser = argparse.ArgumentParser(
            prog="polly peaks_in_pixel_space_single",
            description="A utility to process KPF etalon data from an "+\
                "individual file, specified by filename. Produces an output "+\
                "mask file with the pixel position of each identified etalon "+\
                "peak, as well as optional diagnostic plots."
            )

parser.add_argument("-f", "--filename", default=DEFAULT_FILENAME)

parser.add_argument("-o", "--orderlets", type=parse_orderlets, default="all")
parser.add_argument("--fit_plot", type=parse_bool, default=False)

parser.add_argument("--outdir", type=lambda p: Path(p).absolute(),
                    default="/scr/jpember/temp")


if __name__ == "__main__":
    
    logger.setLevel(logging.INFO)
    
    args = parser.parse_args()
    OUTDIR = args.outdir
    
    main(
        filename = args.filename,
        orderlets = args.orderlets,
        fit_plot = args.fit_plot,
        )