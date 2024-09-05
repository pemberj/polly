#!/usr/bin/env python

"""
Single file analysis command-line utility. Can be passed a filename as argument.
"""


from __future__ import annotations
from pathlib import Path
from astropy.io import fits
from matplotlib import pyplot as plt

try:
    from polly.etalonanalysis import Spectrum
    from polly.plotStyle import plotStyle
except ImportError:
    from etalonanalysis import Spectrum
    from plotStyle import plotStyle
plt.style.use(plotStyle)


TIMESOFDAY = ["morn", "eve", "night"]

ORDERLETS : list[str] = [
    "SCI1",
    "SCI2",
    "SCI3",
    "CAL",
    "SKY"
    ]


def main(
    filename: str,
    orderlets: str | list[str] | None,
    spectrum_plot: bool = False,
    fsr_plot: bool = True,
    ) -> None:
    
    if isinstance(orderlets, str):
        orderlets = [orderlets]
    
    date = "".join(fits.getval(filename, "DATE-OBS").split("-"))
    timeofday = fits.getval(filename, "OBJECT").split("-")[-1]
    assert timeofday in TIMESOFDAY
        
    pp = f"{f'[{date} {timeofday:>5}]':<20}" # Print/logging line prefix

    s = Spectrum(
        spec_file = filename,
        wls_file = None, # Package will locate the corresponding date/time file
        orderlets_to_load = orderlets,
        pp = pp
        )
    s.locate_peaks(fractional_height=0.01, window_to_save=10)
    s.fit_peaks(type="conv_gauss_tophat")
    s.filter_peaks(window=0.1)       
    
    Path(f"{OUTDIR}").mkdir(parents=True, exist_ok=True) # Make OUTDIR
    for ol in s.orderlets:
        s.save_peak_locations(
            filename = f"{OUTDIR}/"+\
                f"{date}_{timeofday}_{ol}_etalon_wavelengths.csv",
            orderlet = ol,
            )

    
        if spectrum_plot:
            for ol in orderlets:
                fig = plt.figure(figsize=(12, 4))
                ax = fig.gca()
                ax.set_title(f"{ol} {date} {timeofday}", size=20)
                ax.set_xlim(440, 880)
                s.plot_spectrum(orderlet=ol, ax=ax, plot_peaks=False)
                ax.legend()
                Path(f"{OUTDIR}/spectrum_plots")\
                    .mkdir(parents=True, exist_ok=True)
                plt.savefig(f"{OUTDIR}/spectrum_plots/"+\
                    f"{date}_{timeofday}_{ol}_spectrum.png")
                plt.close()

        if fsr_plot:
            for ol in s.orderlets:
                fig = plt.figure(figsize=(12, 4))
                ax = fig.gca()
                ax.set_title(f"{ol} {date} {timeofday}", size=20)
                ax.set_xlim(440, 880)
                # ax.set_ylim(30.15, 30.35)
                s.plot_FSR(orderlet=ol, ax=ax)
                ax.legend()
                Path(f"{OUTDIR}/FSR_plots")\
                    .mkdir(parents=True, exist_ok=True)
                plt.savefig(f"{OUTDIR}/FSR_plots/"+\
                    f"{date}_{timeofday}_{ol}_etalon_FSR.png")
                plt.close()


import argparse
parser = argparse.ArgumentParser(
            prog="polly run_analysis_single",
            description="A utility to process KPF etalon data from "+\
                "an individual file. Produces an output file with the "+\
                "wavelengths of each identified etalon peak, as well as "+\
                "diagnostic plots."
                    )

parser.add_argument("-f", "--filename", type=str)
parser.add_argument("-o", "--orderlets", type=str, choices=ORDERLETS, default="SCI2")
parser.add_argument("--outdir", type=str, default="/scr/jpember/temp")
parser.add_argument("--spectrum_plot", type=bool, default=True)
parser.add_argument("--fsr_plot", type=bool, default=True)
parser.add_argument("-v", "--verbose", action="store_true")  # on/off flag

if __name__ == "__main__":
    
    args = parser.parse_args()
    OUTDIR = args.outdir
    
    # logging.basicConfig(filename="/scr/jpember/test.log", level=logging.INFO)
    
    test_filename = "/data/kpf/masters/20240515/"+\
                    "kpf_20240515_master_WLS_autocal-etalon-all-eve_L1.fits"
    
    main(
        # filename = args.filename,
        filename = test_filename,
        orderlets = args.orderlets,
        spectrum_plot = args.spectrum_plot,
        fsr_plot = args.fsr_plot,
        )