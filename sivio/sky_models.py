import os
import random
from math import sin, cos, acos
import logging

import numpy as np
import pandas as pd
import yaml
from yaml import SafeLoader as SafeLoader
from numba import prange, njit
from astroquery.vizier import Vizier
from astropy.coordinates import Angle
import sys

log = logging.getLogger(__name__)


def great_circle_dist1(r1, d1, r2, d2):
    return acos(sin(d1) * sin(d2) + cos(d1) * cos(d2) * cos(r1 - r2))


# def deg2rad(x):
#     return x * np.pi / 180.0


def precise_dist(ra1, dec1, ra2, dec2):
    d1 = np.deg2rad(dec1)
    d2 = np.deg2rad(dec2)
    r1 = np.deg2rad(ra1)
    r2 = np.deg2rad(ra2)
    dist = great_circle_dist1(r1, d1, r2, d2)
    dist = dist * 180.0 / np.pi
    return dist


def random_sky_model(
    N, ra0, dec0, ra_radius=24, dec_radius=18, save=True, filename="sky_model.csv"
):
    ras = sample_floats(ra0 - ra_radius, ra0 + ra_radius, size=N)
    decs = sample_floats(dec0 - dec_radius, dec0 + dec_radius, size=N)

    # fluxes = sample_floats(0.5, 15, size=N)
    # make proper source  count fluxes and pick N fluxes randomly
    sky_fluxes = make_fluxes(sky_type="random")
    fluxes = sky_fluxes[np.random.choice(len(sky_fluxes), size=N, replace=False)]

    ras = np.array(ras)
    ras = np.where(ras < 0, ras + 360, ras)
    decs = np.array(decs)
    fluxes = np.array(fluxes)

    # log.info("RAs range", ras.min(), ras.max())
    # log.info("Decs range", decs.min(), decs.max())
    # log.info("Fluxes range", fluxes.min(), fluxes.max())

    df = pd.DataFrame(
        list(zip(list(ras), list(decs), list(fluxes))), columns=["ra", "dec", "flux"],
    )
    if save:
        df.to_csv("%s" % (filename))
    return ras, decs, fluxes


def make_fluxes(
    sky_type,
    fluxes=0,
    seed=0,
    k1=4100,
    gamma1=1.59,
    k2=4100,
    gamma2=2.5,
    flux_low=1,  # 40e-3,
    flux_mid=5.0,  # 1,
    flux_high=15.0,  # 5.0,
):
    if sky_type == "random":
        np.random.seed(seed)
        fluxes = stochastic_sky(
            seed, k1, gamma1, k2, gamma2, flux_low, flux_mid, flux_high
        )
    elif sky_type == "point":
        fluxes = np.array(fluxes)
    return fluxes


# def generate_distribution(mean, sigma, size, dist, type="ra"):
#     """
#     #Other distribution types
#     if dist == "constant":
#         return np.ones(size) * mean
#     elif dist == "lognormal":
#         return np.random.lognormal(loc=mean,
#                                    sigma=sigma,
#                                    size=size)
#     """
#     if dist == "normal":
#         d = np.random.normal(loc=mean, scale=sigma, size=size)
#         if type == "ra":
#             log.info("RAs range", d.min(), d.max())
#             d = np.where(d < 0, d + 360, d)
#         elif type == "dec":
#             log.info("Decs range", d.min(), d.max())
#         else:
#             d = np.random.normal(loc=mean, scale=sigma, size=size)
#         return d

#     else:
#         raise ValueError("Unrecognised distribution ({}).".format(dist))


def loadfile(data_file, n_sources, ra0, dec0, filename="sky_model.csv"):
    with open(data_file, "r") as f:
        unpacked = yaml.load(f, Loader=SafeLoader)

    flux = []
    ra = []
    dec = []
    names = []
    ampscales = []
    stds = []
    sourcelist = unpacked["sources"]
    for source in sourcelist:
        # log.info(unpacked['sources'][source]['name'])
        names.append(unpacked["sources"][source]["name"])
        dec.append(unpacked["sources"][source]["dec"])
        ra.append(unpacked["sources"][source]["ra"])
        flux.append(unpacked["sources"][source]["flux_density"])
        ampscales.append(np.nanmedian(unpacked["sources"][source]["amp_scales"]))
        stds.append(np.nanstd(unpacked["sources"][source]["amp_scales"]))
    df = pd.DataFrame(
        list(zip(ra, dec, ampscales, stds, flux, names)),
        columns=["ra", "dec", "ampscales", "stds", "flux", "names"],
    )
    df2 = df.dropna(axis=0)

    ra0 = np.rad2deg(ra0)
    dec0 = np.rad2deg(dec0)
    df3 = df2[
        (df2.ra < ra0 + 9)
        & (df2.ra > ra0 - 9)
        & (df2.dec > dec0 - 8.1)
        & (df2.dec < dec0 + 8.9)
    ]
    log.info(df3.shape, df3.ra.max(), df3.ra.min(), df3.dec.max(), df3.dec.min())
    df3 = df3.nlargest(n_sources, "flux", keep="all")

    if filename not in os.listdir(os.path.abspath(".")):
        log.info('saving model"s RTS data products to csv file..')
        df3.to_csv("%s" % (filename))

        log.info(df3.shape)
        ras = np.array(df3.ra)
        decs = np.array(df3.dec)
        fluxes = np.array(df3.flux)

        log.info("RAs range", ras.min(), ras.max())
        log.info("Decs range", decs.min(), decs.max())
        log.info("Fluxes range", fluxes.min(), fluxes.max())
        return ras, decs, fluxes


def sample_floats(low, high, size=1):
    """Return a k-length list of unique random floats
    in the range of low <= x <= high
    """
    result = []
    seen = set()
    for i in range(size):
        x = random.uniform(low, high)
        while x in seen:
            x = random.uniform(low, high)
        seen.add(x)
        result.append(x)
    return result


def stochastic_sky(
    seed=0, k1=4100, gamma1=1.59, k2=4100, gamma2=2.5, S_low=400e-3, S_mid=1, S_high=5.0
):
    np.random.seed(seed)

    # Franzen et al. 2016
    # k1 = 6998, gamma1 = 1.54, k2=6998, gamma2=1.54
    # S_low = 0.1e-3, S_mid = 6.0e-3, S_high= 400e-3 Jy

    # Cath's parameters
    # k1=4100, gamma1 =1.59, k2=4100, gamma2 =2.5
    # S_low = 0.400e-3, S_mid = 1, S_high= 5 Jy

    if S_low > S_mid:
        norm = (
            k2 * (S_high ** (1.0 - gamma2) - S_low ** (1.0 - gamma2)) / (1.0 - gamma2)
        )
        n_sources = np.random.poisson(norm * 2.0 * np.pi)
        # generate uniform distribution
        uniform_distr = np.random.uniform(size=n_sources)
        # initialize empty array for source fluxes
        source_fluxes = np.zeros(n_sources)
        source_fluxes = (
            uniform_distr * norm * (1.0 - gamma2) / k2 + S_low ** (1.0 - gamma2)
        ) ** (1.0 / (1.0 - gamma2))
    else:
        # normalisation
        norm = k1 * (S_mid ** (1.0 - gamma1) - S_low ** (1.0 - gamma1)) / (
            1.0 - gamma1
        ) + k2 * (S_high ** (1.0 - gamma2) - S_mid ** (1.0 - gamma2)) / (1.0 - gamma2)
        # transition between the one power law to the other
        mid_fraction = (
            k1
            / (1.0 - gamma1)
            * (S_mid ** (1.0 - gamma1) - S_low ** (1.0 - gamma1))
            / norm
        )
        n_sources = np.random.poisson(norm * 2.0 * np.pi)

        #########################
        # n_sources = 1e5
        #########################

        # generate uniform distribution
        uniform_distr = np.random.uniform(size=n_sources)
        # initialize empty array for source fluxes
        source_fluxes = np.zeros(n_sources)

        source_fluxes[uniform_distr < mid_fraction] = (
            uniform_distr[uniform_distr < mid_fraction] * norm * (1.0 - gamma1) / k1
            + S_low ** (1.0 - gamma1)
        ) ** (1.0 / (1.0 - gamma1))

        source_fluxes[uniform_distr >= mid_fraction] = (
            (uniform_distr[uniform_distr >= mid_fraction] - mid_fraction)
            * norm
            * (1.0 - gamma2)
            / k2
            + S_mid ** (1.0 - gamma2)
        ) ** (1.0 / (1.0 - gamma2))
    return source_fluxes


def read_gleam(
    ra0,
    dec0,
    radius=20,
    n_sources=None,
    min_flux_cutoff=None,
    catalog="VIII/100/gleamegc",
    filename="unnamed_sky_model.txt",
    write=True,
):
    Vizier.ROW_LIMIT = -1
    catalog = Vizier.query_region(
        f"{ra0} {dec0}", radius=Angle(radius, "deg"), catalog=catalog
    )

    names = catalog[0]["GLEAM"]
    ras = catalog[0]["RAJ2000"]
    decs = catalog[0]["DEJ2000"]
    alphas = catalog[0]["alpha"]
    ref_fluxes = catalog[0]["Fp151"]

    # df = pd.read_csv(csvfile, sep=";")
    # df2 = df[df["Fp151"] > 4]
    # df2 = df2.dropna(axis=0)

    # log.info(df2.shape)
    # names = np.array(df2.GLEAM)
    # ras = np.array(df2.RAJ2000)
    # ras = np.where(ras < 0, ras + 360, ras)
    # decs = np.array(df2.DEJ2000)

    # alphas = np.array([float(i) for i in df2.alpha])
    log.info(
        f"Found {len(names)} sources in total from the {radius} degrees radius sky patch."
    )

    # ref_fluxes = np.array(df2.Fp151)
    nan_mask = ~np.isnan(alphas)
    names, ras, decs, alphas, ref_fluxes = [
        x[nan_mask] for x in [names, ras, decs, alphas, ref_fluxes]
    ]

    if n_sources:
        if len(ref_fluxes) < n_sources:
            log.info(
                f"Warning: You asked for {n_sources} sources. \
                The GLEAM catalogue has only {len(ref_fluxes)} sources in the specified sky area.\
                Using all available sources."
            )
        else:
            n_brightest_mask = (-ref_fluxes).argsort()[:n_sources]
            names, ras, decs, alphas, ref_fluxes = [
                x[n_brightest_mask] for x in [names, ras, decs, alphas, ref_fluxes]
            ]
            log.info(f"Obtained the {n_sources} brightest sources")

    if min_flux_cutoff:
        flux_cutoff_mask = ref_fluxes > min_flux_cutoff
        if not np.any(flux_cutoff_mask):
            log.info(
                "Sorry. No sources with flux density above the specified minimum cutoff. Exiting."
            )
            sys.exit()
        else:
            names, ras, decs, alphas, ref_fluxes = [
                x[flux_cutoff_mask] for x in [names, ras, decs, alphas, ref_fluxes]
            ]
            log.info(
                f"Found {len(ras)} sources above minimum flux density cuttoff. Using those."
            )

    ras = np.where(ras < 0, ras + 360, ras)
    if write:
        write_model(names, ras, decs, alphas, ref_fluxes, filename)
    return names, ras, decs, alphas, ref_fluxes


@njit(parallel=True)
def gleam_model_spectrum(ras, decs, alphas, ref_fluxes, frequencies):
    fluxes = np.zeros((len(ras), len(frequencies), 4), dtype=np.float32)
    for source in prange(fluxes.shape[0]):
        for freq_chan in prange(len(frequencies)):
            fluxes[source, freq_chan, 0] = (
                ref_fluxes[source] * (frequencies[freq_chan] / 151e6) ** alphas[source]
            )
            # fluxes[source, :, 0] = compute_channel_fluxes(
            #     ref_fluxes[source], 151e6, alphas[source], frequencies
            # )
            fluxes[source, freq_chan, 3] = fluxes[
                source, freq_chan, 0
            ]  # Both XX and YY

    return fluxes


def write_model(names, ras, decs, alphas, ref_fluxes, filename):
    fname = open(filename, "w")
    faa = np.pi ** 2.0
    fbb = 2.0 * np.log(2.0)
    factor = np.sqrt(faa / fbb)

    mfreqs = np.arange(100, 243, 13)
    # print("mfreqs", mfreqs)
    for name, ra, dec, alpha, ref_flux in zip(names, ras, decs, alphas, ref_fluxes):
        maj = float(0)
        mnr = float(0)
        pa = float(0)
        line0 = f"SOURCE {name} {str(ra / 15.0)} {str(dec)}"

        fname.write(line0 + "\n")
        if maj != 0 or mnr != 0:  # Gaussian simulation not implemented yet
            line1 = f"GAUSSIAN {str(pa)} {str(maj * factor * 60.0)} {str(mnr * factor * 60.0)}"
            fname.write(line1 + "\n")

        for ff in range(len(mfreqs)):
            mod_flx = power_law(ref_flux, alpha, mfreqs[ff])
            line2 = f"FREQ {str(mfreqs[ff])}e+6 {str(mod_flx)} 0 0 0"
            fname.write(line2 + "\n")
        line3 = "ENDSOURCE"
        fname.write(line3 + "\n")

    fname.close()
    return


def power_law(norm, alpha, nu):
    return norm * (nu / 151.0) ** alpha


if __name__ == "__main__":
    frequencies = np.linspace(100, 130, 768) * 1e6
    names, ras, decs, alphas, ref_fluxes = read_gleam(
        0.0, -27.0, radius=20, n_sources=9000, min_flux_cutoff=0.4
    )

    log.info([x.shape for x in [names, ras, decs, alphas, ref_fluxes]])
    fluxes = gleam_model_spectrum(ras, decs, alphas, ref_fluxes, frequencies)

    log.info(ras)
    log.info(decs)
    log.info(fluxes.shape)
    # log.info(fluxes[:, 0, 1])
    print(fluxes[:, -1, 3])
