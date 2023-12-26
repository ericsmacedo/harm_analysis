import numpy as np
from scipy import signal
    # values of DC bins
import matplotlib.pyplot as plt


__all__ = ["harm_analysis"]


def _arg_x_as_expected(value):
    """Ensure argument `x` is a 1-D C-contiguous array of dtype('float64').

    Used in `find_peaks`, `peak_prominences` and `peak_widths` to make `x`
    compatible with the signature of the wrapped Cython functions.

    Returns
    -------
    value : ndarray
        A 1-D C-contiguous array with dtype('float64').
    """
    value = np.asarray(value, order='C', dtype=np.float64)
    if value.ndim != 1:
        raise ValueError('`x` must be a 1-D array')
    return value


def _win_metrics(x):
    """
    Compute the coherent gain and the equivalent noise bandwidth of a window.

    Parameters
    ----------
    x : array_like
        Input window. The window should be normalized so that its DC value is 1.

    Returns
    -------
    coherent_gain : float
        Gain added by the window. Equal to its DC value.
    eq_noise_bw : float
        Window equivalent noise bandwidth, normalized by noise power per bin (N0/T).
    """
    # Gain added by the window. Equal to its DC value
    coherent_gain = np.sum(x)

    # Equivalent noise bandwidth of the window, in number of FFT bins
    eq_noise_bw = np.sum(x**2)/coherent_gain**2

    return coherent_gain, eq_noise_bw


def _fft_pow(x: np.ndarray, win: np.ndarray, n_fft: int, FS: float = 1,
             coherent_gain: float = 1):
    """
    Calculate the single-sided power spectrum of the input signal.

    Parameters
    ----------
    x : numpy.ndarray
        Input signal.
    win : numpy.ndarray
        Window function to be applied to the input signal `x` before
        computing the FFT.
    n_fft : int
        Number of points to use in the FFT (Fast Fourier Transform).
    FS : float, optional
        Sampling frequency of the input signal `x`. Defaults to 1.
    coherent_gain : float, optional
        Coherent gain factor applied to the FFT result. Defaults to 1.

    Returns
    -------
    x_fft_pow : numpy.ndarray
        Single-sided power spectrum of the input signal `x`.
    f_array : numpy.ndarray
        Array of positive frequencies corresponding to the single-sided power spectrum.
    """

    # Positive frequencies of the FFT(x*win)
    x_fft = np.fft.rfft(x*win, n_fft)
    f_array = np.fft.rfftfreq(n_fft, 1/FS)

    # Obtain absolute value and remove gain added by the window used
    x_fft_abs = np.abs(x_fft)/coherent_gain

    # Single-sided power spectrum
    x_fft_pow = x_fft_abs**2
    x_fft_pow[1:] *= 2

    return x_fft_pow, f_array


def _find_freq_bins(x_fft: np.array, freq: np.array) -> np.array:
    '''Find frequency Bins of fundamental and harmonics

    Finds the frequency bins of frequencies. The end/start of a frequency
    is found by comparing the amplitude of the bin on the rigth/left.
    The frequency harmonic ends when the next bin is greater than the
    current bin.

    Arguments
    ---------
    x_fft:
        Absolute value of FFT from DC to Fs/2

    frequencies:
        List of frequencies to look for.

    Returns:
        list of bin bins index
    '''
    fft_length = len(x_fft)

    # find local maximum near bin
    dist = 3
    idx0 = max(freq-dist, 0)
    idx1 = freq+dist+1

    max_idx = np.argmax(x_fft[idx0:idx1])
    freq = max_idx + freq - dist

    start = freq
    end = freq
    MAX_N_SMP = 30
    # find end of peak (right side)
    for i in range(fft_length - freq - 1):
        if x_fft[freq+i] - x_fft[freq+i+1] <= 0 or (i > MAX_N_SMP):
            end = freq+i+1
            break

    # find end of peak (left side)
    for i in range(fft_length - freq - 1):
        if (x_fft[freq-i] - x_fft[freq-(i+1)] <= 0) or (i > MAX_N_SMP):
            start = freq-i
            break

    bin_values = np.arange(start, end).astype(int)

    return bin_values


def _find_dc_bins(x_fft: np.array) -> np.array:
    '''
    Find DC bins of FFT output

    Finds the DC bins. The end of DC is found by checking the amplitude of
    the consecutive bins. DC ends when the next bin is greater than
    the current bin.

    Parameters
    ---------
    x_fft : array_like
            Absolute value of the positive frequencies of FFT

    Returns
    -------

    '''
    # Stop if DC is not found after 50 samples
    return np.argmax(np.diff(x_fft[:50]) > 0) + 1


def _find_bins(x, n_harm):
    """
    Find all bins that belong to the fundamental, harmonics, DC, and noise.

    Parameters
    ----------
    x : ndarray
        Input signal. The input should be the absolute value of the right-sided power
        spectrum.
    n_harm : int
        Number of harmonics to find

    Returns
    -------
    fund_bins : ndarray
        Bins of fundamental frequency
    harm_loc : ndarray
        Locations of harmonics
    harm_bins : ndarray
        Bins of harmonics
    dc_bins : ndarray
        Bins of DC component
    noise_bins : ndarray
        Bins of noise

    Notes
    -----
    This function only works for the right-sided power spectrum (positive frequencies
    only).
    """
    max_bin = len(x)

    # Index of last dc bin
    dc_end = _find_dc_bins(x)
    dc_bins = np.arange(dc_end)

    # the fundamental frequency is found by searching for the bin with the
    # maximum value, excluding DC
    fund_loc = np.argmax(x[dc_end:]) + dc_end

    # list containing bins of fundamental
    fund_bins = _find_freq_bins(x, fund_loc)

    # calculate the frequency of the harmonics.
    # frequencies > fs/2 are ignored
    harm_loc = fund_loc*np.arange(2, n_harm+2)
    harm_loc = harm_loc[harm_loc <= max_bin]

    # Obain bins related to the harmonics of the fundamental frequency
    harm_bins = np.concatenate([_find_freq_bins(x, loc) for loc in harm_loc])

    # Remaining bins are considered noise.
    noise_bins = np.setdiff1d(np.arange(len(x)),
                              np.concatenate((fund_bins, harm_bins, dc_bins)))

    return fund_bins, harm_loc, harm_bins, dc_bins, noise_bins


def _mask_array(x, idx_list):
    """
    Mask an array so that only the values at the specified indices are valid.

    Parameters
    ----------
    x : array_like
        Input array.
    idx_list : list of int
        List of indices to keep.

    Returns
    -------
    masked_array : MaskedArray
        A masked array with the same shape as `x`, where only the values at the
        indices in `idx_list` are valid.

    Examples
    --------
    >>> x = np.array([1, 2, 3, 4, 5])
    >>> idx_list = [0, 2, 4]
    >>> mask_array(x, idx_list)
    masked_array(data=[1, --, 3, --, 5],
                 mask=[False,  True, False,  True, False],
           fill_value=999999)
    """
    mask = np.zeros_like(x, dtype=bool)
    mask[idx_list] = True
    return np.ma.masked_array(x, mask=~mask)


def _plot(x: np.array,
          freq_array: np.ndarray,
          dc_bins: np.ndarray,
          fund_bins: np.ndarray,
          harm_bins: np.ndarray,
          noise_bins: np.ndarray,
          ax):

    x_db = 10*np.log10(x)

    fund_array = _mask_array(x_db, fund_bins)
    harm_array = _mask_array(x_db, harm_bins)
    dc_noise_array = _mask_array(x_db, np.concatenate((dc_bins, noise_bins)))
    total_noise_array = _mask_array(x, np.concatenate((harm_bins, noise_bins)))

    int_noise_curve = 10*np.log10(np.cumsum(total_noise_array))

    ax.plot(freq_array, fund_array, label="Fundamental", linewidth=0.7)
    ax.plot(freq_array, harm_array, label="Harmonics", linewidth=0.7)
    ax.plot(freq_array, dc_noise_array, label="DC and Noise", linewidth=0.7,
            color='black')
    ax.plot(freq_array, int_noise_curve, label="Integrated total noise",
            linewidth=0.7, color='green')
    ax.legend()
    ax.grid()

    ax.set_ylabel("[dB]")
    ax.set_xlabel("[Hz]")

    return ax


def _get_integ_noise_curve(x: np.array,
                           enbw_bins: float,
                           f_array: np.array,
                           fund_bins: np.array,
                           harm_bins: np.array,
                           dc_bins: np.array):

    noise_fft = np.copy(x)
    # ingore DC and fundamental. Integrate all the rest
    dc_end = max(dc_bins) + 1
    noise_fft[fund_bins] = 0
    # noise_fft[harm_bins] = 0

    intg_noise = 10*np.log10(np.cumsum(noise_fft[dc_end:])/enbw_bins)

    fn_array = f_array[dc_end:]

    return fn_array, intg_noise


def harm_analysis(x: np.array,
                  FS: float = 1,
                  n_harm: int = 5,
                  window: np.array = None,
                  plot=False,
                  ax=None) -> dict:
    '''Calculate SNR, THD, Fundamental power, and Noise power of the input signal x.

    The total harmonic distortion is determined from the fundamental frequency and the
    first five harmonics using a power spectrum of the same length as the input signal.
    A hann window is applied to the signal, before the power spectrum is obtained.

    Parameters
    ----------
    x : array_like
        Input signal, containing a tone.
    FS : float, optional
         Sampling frequency.
    n_harm : int, optional
             Number of harmonics used in the THD calculation.
    window : array_like, optional
             Window that will be multiplied with the signal. Default is
             Hann squared.
    plot : bool or None, optional
           If True, the power spectrum result is plotted. If specified,
           an `ax` must be provided, and the function returns a dictionary
           with the results and the specified axes (`ax`). If plot is not set,
           only the results are returned.
    ax : plt.Axes or None, optional
         Axes to be used for plotting. Required if plot is set to True.

    Returns
    -------
    dict
        A dictionary containing the analysis results:
        - 'fund_db': Fundamental power in decibels (sig_pow_db),
        - 'fund_freq': Frequency of the fundamental tone (sig_freq),
        - 'dc_db': DC power in decibels (dc_db),
        - 'noise_db': Noise power in decibels (noise_pow_db),
        - 'thd_db': Total harmonic distortion in decibels (thd_db),
        - 'snr_db': Signal-to-noise ratio in decibels (snr_db),
        - 'thdn_db': Total harmonic distortion plus noise in decibels (thdn_db).
    plt.axes
        If plot is set to True, the Axes used for plotting is returned.

    Notes
    -----
    The function fails if the fundamental is not the highest spectral component in the
    signal.

    Ensure that the frequency components are far enough apart to accommodate for the
    sidelobe width of the Hann window. If this is not feasible, you can use a different
    window by using the "window" input.

    References
        ----------
        .. [1] Harris, Fredric J. "On the use of windows for harmonic analysis
               with the discrete Fourier transform." *Proceedings of the
               IEEE* 66.1 (1978): 51-83.
        .. [2] Cerna, Michael, and Audrey F. Harvey. *The fundamentals of
               FFT-based signal analysis and measurement*. Application Note
               041, National Instruments, 2000.
    '''

    sig_len = len(x)

    if window is None:
        window = signal.windows.hann(sig_len, sym=False)

    # window metrics
    coherent_gain, enbw = _win_metrics(window)
    enbw_bins = enbw*sig_len

    # Obtain the single-sided power spectrum
    x_fft_pow, f_array = _fft_pow(x=x, win=window, n_fft=sig_len, FS=FS,
                                  coherent_gain=coherent_gain)

    fund_bins, harm_loc, harm_bins, dc_bins, noise_bins = _find_bins(x=x_fft_pow,
                                                                     n_harm=n_harm)

    fund_power = np.sum(x_fft_pow[fund_bins]/enbw_bins)
    harm_power = np.sum(x_fft_pow[harm_bins]/enbw_bins)
    dc_power = np.sum(x_fft_pow[dc_bins]/enbw_bins)
    noise_power = np.sum(x_fft_pow[noise_bins]/enbw_bins)

    sig_freq = np.average(fund_bins, weights=x_fft_pow[fund_bins]) * FS/sig_len

    # Calculate THD, Signal Power and N metrics in dB
    thd_db = 10*np.log10(harm_power/fund_power)
    thdn_db = 10*np.log10(harm_power/fund_power+noise_power)
    sig_pow_db = 10*np.log10(fund_power)
    noise_pow_db = 10*np.log10(noise_power)
    snr_db = sig_pow_db - noise_pow_db
    dc_db = 10*np.log10(dc_power)

    results = {'fund_db': sig_pow_db,
               'fund_freq': sig_freq,
               'dc_db': dc_db,
               'noise_db': noise_pow_db,
               'thd_db': thd_db,
               'snr_db': snr_db,
               'thdn_db': thdn_db}

    if plot is False:
        return results
    else:
        ax = _plot(x=x_fft_pow, freq_array=f_array, dc_bins=dc_bins,
                   fund_bins=fund_bins, harm_bins=harm_bins, noise_bins=noise_bins,
                   ax=ax)

        return results, ax
