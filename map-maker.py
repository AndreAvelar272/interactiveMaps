import pandas as pd
import folium
from datetime import datetime
import argparse
import os
import re
from math import radians, sin, cos, sqrt, atan2

def parse_arguments():
    parser = argparse.ArgumentParser(description='Create a map from a CSV file with GPS data.')
    parser.add_argument('csv_file', type=str, help='Path to the input CSV file.')
    parser.add_argument('-o', '--output', type=str, default='map.html', help='Output HTML file for the map.')
    parser.add_argument('--remove-duplicates', action='store_true', help='Remove duplicate entries.')
    return parser.parse_args()

def read_csv(csv_file):
    try:
        df = pd.read_csv(
            csv_file,
            delimiter=',',  # Changed from ';' to ','
            quotechar='"',
            escapechar='\\',
            encoding='utf-8'
        )
        return df
    except Exception as e:
        print(f"Error reading CSV file: {e}")
        exit(1)

def parse_timestamp(timestamp_str):
    # Example format: "Jun 28, 2024 @ 13:59:38.831"
    try:
        return datetime.strptime(timestamp_str, '%b %d, %Y @ %H:%M:%S.%f')
    except ValueError as e:
        print(f"Timestamp parsing error: {e} for timestamp {timestamp_str}")
        return None

def extract_coordinates(position_str):
    try:
        # Extract the numbers using regex
        match = re.match(r'POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)', position_str)
        if not match:
            raise ValueError("Position string does not match 'POINT (x y)' format.")
        lon, lat = map(float, match.groups())
        return [lat, lon]  # Folium uses [latitude, longitude]
    except Exception as e:
        print(f"Error parsing position: {e} for position {position_str}")
        return None

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate the Haversine distance between two points on the Earth in kilometers.
    
    Parameters:
    - lat1, lon1: Latitude and Longitude of point 1 in decimal degrees
    - lat2, lon2: Latitude and Longitude of point 2 in decimal degrees
    
    Returns:
    - Distance in kilometers as a float
    """
    R = 6371.0  # Earth radius in kilometers

    # Convert decimal degrees to radians
    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)

    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    distance = R * c
    return distance

def process_data(df, remove_duplicates=False):
    # Parse timestamps
    df['parsed_timestamp'] = df['timestamp'].apply(parse_timestamp)
    df = df.dropna(subset=['parsed_timestamp'])

    # Extract coordinates
    df['coords'] = df['position'].apply(extract_coordinates)
    df = df.dropna(subset=['coords'])

    if remove_duplicates:
        df = df.drop_duplicates()

    # Sort by timestamp
    df = df.sort_values('parsed_timestamp').reset_index(drop=True)

    # Assign sequence numbers
    df['sequence'] = df.index + 1  # Starts from 1

    # Calculate Haversine distance to the previous point
    # Separate previous latitude and longitude
    df['prev_lat'] = df['coords'].apply(lambda x: x[0]).shift(1)
    df['prev_lon'] = df['coords'].apply(lambda x: x[1]).shift(1)

    # Create previous timestamp
    df['prev_time'] = df['parsed_timestamp'].shift(1)

    # Calculate time difference in hours
    df['time_diff_hours'] = (df['parsed_timestamp'] - df['prev_time']).dt.total_seconds() / 3600

    # Calculate distance_km
    def calculate_distance(row):
        if pd.isnull(row['prev_lat']) or pd.isnull(row['prev_lon']):
            return 0.0  # No predecessor
        lat1, lon1 = row['prev_lat'], row['prev_lon']
        lat2, lon2 = row['coords']
        return haversine(lat1, lon1, lat2, lon2)

    df['distance_km'] = df.apply(calculate_distance, axis=1)

    # Calculate average speed in km/h
    def calculate_avg_speed(row):
        if row['sequence'] == 1:
            return "N/A"  # No predecessor
        if row['time_diff_hours'] <= 0:
            return "N/A"  # Avoid division by zero or negative time differences
        speed = row['distance_km'] / row['time_diff_hours']
        return f"{speed:.2f} km/h"

    df['avg_speed_kmh'] = df.apply(calculate_avg_speed, axis=1)

    # Optionally, drop the 'prev_lat', 'prev_lon', 'prev_time', 'time_diff_hours' columns as they're no longer needed
    df = df.drop(columns=['prev_lat', 'prev_lon', 'prev_time', 'time_diff_hours'])

    return df

def create_map(df, output_file):
    if df.empty:
        print("No data available to plot.")
        return

    # Calculate the average location for initial map centering
    avg_lat = df['coords'].apply(lambda x: x[0]).mean()
    avg_lon = df['coords'].apply(lambda x: x[1]).mean()

    m = folium.Map(location=[avg_lat, avg_lon], zoom_start=15)

    # Add numbered pin-like markers using folium.DivIcon
    for idx, row in df.iterrows():
        # Format distance
        if row['sequence'] == 1:
            distance_str = "N/A"
            speed_str = "N/A"
        else:
            distance_str = f"{row['distance_km']:.2f} km"
            speed_str = row['avg_speed_kmh']

        # Create HTML content for the popup
        popup_html = (
            f"<b>Time:</b> {row['parsed_timestamp']}<br>"
            f"<b>Country Code:</b> {row['country_code']}<br>"
            f"<b>Route ID:</b> {row['route_id']}<br>"
            f"<b>Distance from Previous:</b> {distance_str}<br>"
            f"<b>Average Speed since Previous:</b> {speed_str}"
        )

        # Create an IFrame to hold the HTML content
        iframe = folium.IFrame(html=popup_html, width=300, height=140)

        # Create the popup using the IFrame
        popup = folium.Popup(iframe, max_width=300, sticky=False, auto_close=False, close_on_click=False)

        folium.Marker(
            location=row['coords'],
            popup=popup,
            icon=folium.DivIcon(
                html=f"""
                <div style="
                    font-size: 12pt;
                    color: black;
                    background-color: white;
                    border-radius: 50%;
                    width: 24px;
                    height: 24px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    border: 2px solid blue;
                ">
                    {row['sequence']}
                </div>
                """
            )
        ).add_to(m)

    # Draw lines between points
    folium.PolyLine(df['coords'].tolist(), color="blue", weight=1.7, opacity=0.5).add_to(m)

    # Optionally, add a start and end marker with different colors
    if not df.empty:
        # Start marker
        start_popup_html = "<b>Start</b>"
        start_iframe = folium.IFrame(html=start_popup_html, width=150, height=50)
        start_popup = folium.Popup(start_iframe, max_width=150, sticky=False, auto_close=False, close_on_click=False)

        folium.Marker(
            location=df.iloc[0]['coords'],
            popup=start_popup,
            icon=folium.Icon(color='green', icon='play')
        ).add_to(m)
        
        # End marker
        end_popup_html = "<b>End</b>"
        end_iframe = folium.IFrame(html=end_popup_html, width=150, height=50)
        end_popup = folium.Popup(end_iframe, max_width=150, sticky=False, auto_close=False, close_on_click=False)

        folium.Marker(
            location=df.iloc[-1]['coords'],
            popup=end_popup,
            icon=folium.Icon(color='red', icon='stop')
        ).add_to(m)

    # Save the map to an HTML file
    try:
        m.save(output_file)
        print(f"Map has been saved to {os.path.abspath(output_file)}")
    except Exception as e:
        print(f"Error saving map: {e}")

def main():
    args = parse_arguments()
    df = read_csv(args.csv_file)
    processed_df = process_data(df, remove_duplicates=args.remove_duplicates)
    create_map(processed_df, args.output)

if __name__ == "__main__":
    main()
