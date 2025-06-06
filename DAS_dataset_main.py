import numpy as np
import os
import time
import matplotlib.pyplot as plt

from sklearn.datasets                   import fetch_openml
from sklearn.model_selection            import train_test_split
from sklearn.metrics                    import classification_report, accuracy_score
from obspy                              import Stream
from models.HDAS_file_convert           import sampling_file_name, HDAS_meas_settings, read_bin_file
from models.Obspy_processing            import create_stream, ram_normalization, show_sort_plot, show_fft
from models.ASDF_file_convert           import write_to_h5
from models.User_print                  import print_header, print_small_header, print_update
from models.Spectrogram_plot            import plot_spectrogram
from models.Spacial_spectrogram         import plot_spatial_spectrogram, plot_spatial_spectrogram_interval, compute_fk_spectrum
from models.Event_analyzer              import analyze_event_dynamics 
from models.Feature_extraction_ML       import extract_csd_matrix
from models.Logistic_Regression         import run_logistic_regression, predict_logistic_regression
from models.PCA                         import fit_pca, transform_pca, get_explained_variance, plot_explained_variance
from datetime                           import datetime

#############################################################################################

Name          = 'Faial Dia 20'                   # Project Name

# When in MODAS PC
# raw_data_file = 'D:\\DAS_FAIAL\\20_01_24 Anomalia\\ProcessedData' # Comment when not in MODAS

# When in Dénis PC
raw_data_file = '/Users/denis/Library/CloudStorage/GoogleDrive-drfafelgueiras@gmail.com/My Drive/Bolsa/20_01_24 Anomalia/ProcessedData' #comment when in MODAS

if os.path.exists(raw_data_file):
    print("Found the folder!")
else:
    print("Path not found.")

# Channel range to load
start_channel = 2000
stop_channel  = 2200
channel_range = list(range(start_channel, stop_channel + 1))    # all channels
select        = [0, 87]    # selecting which ones to monitor
# select =  channel_range.copy()                         # all channels for feature extration of all channels
select_spatial = list(range(len(channel_range)))                # all channels for spatial spectrogram

window_norm   = 10.0                                            # running average window for time-domain normalization [s]
band_freq     = [0.01, 10.0]                                    # Band pass filter [f_cut_min, f_cut_high] [Hz]

# Metadata
start_time = '2025-01-20-12-00-07'                              # Starting time ('%Year-%month-%day-%Hour-%Minutes-%Seconds')
station    = 'FAIAL'                                            # Station Name
network    = 'MODAS'                                            # Network Name
location   = 'FAIAL'                                            # Location Name

#############################################################################################
# Step 0. Find Data
save_data_folder = os.path.join(os.getcwd(), 'Code', 'data', 'results')
raw_data_folder  = raw_data_file
sampling_files   = sampling_file_name(raw_data_folder)

meas_settings    = HDAS_meas_settings( sampling_files[0] )
n_time_samples   = meas_settings['N Time Samples']          # Determine the number of time samples
n_channels       = int(meas_settings['N Processed'])        # Determine the number of position samples
frequency_sample = meas_settings['Sample Frequency']        # Determine the frequency of aquisition
spatial_sample   = meas_settings['Spatial Sampling']        # Determine the lenght separation
offset           = meas_settings['Pos Offset']              # Determine the lenght offset


aquisition_time  = n_time_samples/frequency_sample          # Determine the total time of aquisition in [s]

##############################################################################################
# Step 0.1 Print Header
args = { 'Project name'   : Name,
         'Fiber lenght'   : f'{n_channels*spatial_sample + offset} m',
         'N channels'     : n_channels,
         'Channel spacing': f'{spatial_sample} m',
         'Spatial offset' : f'{offset} m',
         'N time samples' : n_time_samples,
         'Aquisition time': f'{aquisition_time/(60*60)} h',
         'Sampling rate'  : f'{frequency_sample} Hz' }

print_header('DAS Raw Data converter', args)

#############################################################################################
# Step 1. Convert data into Obspy.stream

start = time.time()
print_small_header('Converting the Data into a stream')

raw_data_2D = np.empty((len(channel_range), n_time_samples))
# Process each file and fill the 2D array
for i, chan_idx in enumerate(channel_range):

    # Read the relevant data slice from each file
    _, FileData, _ = read_bin_file(sampling_files[chan_idx], skip_header=True)

    # Check and replace NaN values
    FileData = np.nan_to_num(FileData, nan=0)

    # Store data values
    raw_data_2D[i] = FileData

channel_list = [f"CH{50 + chan_idx * 10}m" for chan_idx in channel_range]
stream       = create_stream(raw_data_2D, frequency_sample, start_time, len(channel_range), channel_list, station, network, location)

# Delete previous data formats to free memory
del FileData, raw_data_2D
print_update(f"Step 1 completed in {time.time() - start:.2f} seconds")

#############################################################################################
# Step 2. Single station analysis

start = time.time()
print_header('Data Treatment')

print_small_header('Single station analysis')

# Select channels to monitor
chn_select = [channel_list[i] for i in select]
st_monitor = Stream()
for chan in chn_select:
    st_monitor += stream.select(channel=chan)

chn_select_spatial = [channel_list[i] for i in select_spatial]
st_monitor_spatial = Stream()
for chan in chn_select_spatial:
    st_monitor_spatial += stream.select(channel=chan)


# show_sort_plot(st_monitor)  # Uncomment to plot Raw data

print_update('Detrending data')
stream.detrend()
st_monitor.detrend()

# show_sort_plot(st_monitor)  # Uncomment to plot Detrended data

print_update('Filtering data')
stream.filter("bandpass", freqmin=band_freq[0], freqmax=band_freq[1], corners=4, zerophase=True)
st_monitor.filter("bandpass", freqmin=band_freq[0], freqmax=band_freq[1], corners=4, zerophase=True)

# show_fft(st_monitor)        # Uncomment to plot filtered data spectrum
# show_sort_plot(st_monitor)  # Uncomment to plot filtered data

#print_update('Normalize data')

#stream = ram_normalization(stream, window_norm)
#st_monitor = ram_normalization(st_monitor, window_norm)

# show_sort_plot(st_monitor_normalized)  # Uncomment to print normalized data

print_update(f"Step 2 completed in {time.time() - start:.2f} seconds")

#############################################################################################
# Step 3. Analysis in Frequency Spectrum

start = time.time()
print_header('Generating spectrograms for selected channels') 

start_datetime = datetime.strptime(start_time, '%Y-%m-%d-%H-%M-%S') #convert time to object

for i in range(len(select)):
    chan_name = st_monitor.traces[i].stats.channel
    print_update(f'Processing spectrogram for channel {chan_name}')
    # time_window: tuple of (start_time_offset, end_time_offset) in seconds
    Sxx, f, t = plot_spectrogram(st_monitor, channel_index=i, fs=frequency_sample, start_time=start_datetime, time_window=(18900, 19800))

print_update(f"Step 3 completed in {time.time() - start:.2f} seconds")
#############################################################################################
# Step 4. Spatial spectrum analysis

start = time.time()
print_header('Generating spatial spectrogram for all channels')

print_update("Plotting Spatial Spectrogram of one specific time")

plot_spatial_spectrogram(stream=st_monitor_spatial, time_window=(0, 43218), fs=frequency_sample, spatial_sample=spatial_sample, window_size=32, overlap=0.9, target_time = 19800)

print_update("Plotting Spatial Spectrogram of time interval")

plot_spatial_spectrogram_interval(stream=st_monitor_spatial, time_window=(0, 43218), fs=frequency_sample, spatial_sample=spatial_sample, window_size=32, overlap=0.9, target_time=19810, interval=0.2)

print_update("Plotting F-K Spectrogram")

n_channels_fk = int(1000 / spatial_sample)
subset_stream = st_monitor_spatial[:n_channels_fk]

compute_fk_spectrum(stream=subset_stream, fs=frequency_sample, spatial_sample=spatial_sample, time_window=(0, 1800))

print_update(f"Step 4 completed in {time.time() - start:.2f} seconds")

#############################################################################################
# Step 5. Analyze Event to get amplitude

print_header('Analyzing Event Signal')

start = time.time()

analyze_event_dynamics(stream=st_monitor, fs=frequency_sample, time_window=(18900, 19800), channel_index="CH20920m",fit_pdf=False)


print_update(f"Step 5 completed in {time.time() - start:.2f} seconds")

#############################################################################################
# Step 6. Feature Extraction of Data Set

start = time.time()

# Extract the date part from start_time
start_datetime = datetime.strptime(start_time, '%Y-%m-%d-%H-%M-%S')
date_str = start_datetime.strftime('%Y-%m-%d')  # Extracting the date in YYYY-MM-DD format

# Create output folders for features
output_folder_features = 'saved_features'
os.makedirs(output_folder_features, exist_ok=True)

print_header('Extracting features for selected channels')

print_update('Converting time to object')

# Select a multichannel window
data_matrix = np.array([tr.data for tr in st_monitor_spatial])
window_start = int(frequency_sample * 18900)
window_end = int(frequency_sample * 19800)
data_matrix = data_matrix[:, window_start:window_end]

# Extract features (CSDM)
csd_feature_vector = extract_csd_matrix(data_matrix, fs=frequency_sample)

print("Cross Spectral Density Matrix has dimensions:", csd_feature_vector.shape)

# Save CSDM features to a file
csd_feature_file_path = os.path.join(output_folder_features, f"csd_features_{date_str}.npy")
np.save(csd_feature_file_path, csd_feature_vector)

# Optionally, print the path where the features are saved
print(f"CSDM features saved to {csd_feature_file_path}")

# Print total execution time
end = time.time()
execution_time = end - start
print(f"Total execution time: {execution_time:.2f} seconds")

#############################################################################################
# Step 7. Apply PCA and then Logistic Regression

print_header('Applying PCA + Logistic Regression')

start = time.time()

#i need to do a train test split

# Suppose X is your (n_samples, n_features) matrix from extract_csd_matrix
csd_feature_reduced = fit_pca(csd_feature_vector, variance_threshold=0.95)  # auto-select components for x% variance

print(csd_feature_reduced)

# Later on, transform new samples with the same PCA
# X_new_reduced = transform_pca(X_new)

print_update(f"Step 7 completed in {time.time() - start:.2f} seconds")

#print_update('saving ASDF data')
#write_to_h5(stream, 'DAS_SSprocess.h5')

#############################################################################################
#Testing my Classifier with MNIST

# Load MNIST data
mnist = fetch_openml('mnist_784', version=1)
X = mnist.data / 255.0  # Normalize
y = mnist.target.astype(int)

# Split into train and test sets
X_train_raw, X_test_raw, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

X_train_pca = fit_pca(X_train_raw, n_components=60)
X_test_pca = transform_pca(X_test_raw)

model, report = run_logistic_regression(X_train_pca, y_train)
y_pred = model.predict(X_test_pca)

print("Accuracy:", accuracy_score(y_test, y_pred))
print(classification_report(y_test, y_pred))