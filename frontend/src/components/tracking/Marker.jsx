// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import React, { useState, useEffect, useCallback, useRef } from "react";
import { Marker as MapMarker, Source, Layer } from "react-map-gl";
import { createGeoJSONCircle } from "./Marker.helpers";
import { Hub } from "@aws-amplify/core";
import {Popup} from "react-map-gl";
import { format } from "date-fns";

export const Marker = ({ isShowingHistory, isTrackingChecked }) => {
  const [marker, setMarker] = useState();
  const [showPopup, setShowPopup] = useState(false);
  const hubRef = useRef();

  const onAssetTrackerUpdate = useCallback(async (update) => {
    const {
      payload: { data, event },
    } = update;
    if (event === "positionUpdate") {
      setMarker(data);
    }
  }, []);

  useEffect(() => {
    hubRef.current = Hub.listen("assetTrackerUpdates", onAssetTrackerUpdate);

    // Clean up the hub listener when the component unmounts
    return () => hubRef.current();
  }, []);

  if (isShowingHistory || !isTrackingChecked) return null;

  return (
    <>
      {marker ? (
        <MapMarker color="teal" latitude={marker.lat} longitude={marker.lng} 
        onClick = { e=> 
          //prevent from closing automatically, because of closeOnCLick 
          //propagating map
          {e.originalEvent.stopPropagation();
          setShowPopup(!showPopup)
        }}
        />
      ) : null}
      {showPopup ? (
        <Popup
          longitude={marker.lng} latitude={marker.lat}
          anchor="top-right"
          onClose={()=> setShowPopup(!showPopup)}
          offset = {20}>
          <p> <strong> Lattitude: </strong> {Math.round(marker.lat * 1000000)/1000000} </p>
          <p> <strong> Longitude: </strong> {Math.round(marker.lng * 1000000)/1000000} </p>
          <p> <strong> Battery: </strong> {marker.metadata.batteryLevel} </p>
          <p> <strong> SampleTime: </strong> {marker.sampleTime} </p>
          <p> <strong> Accuracy: </strong> {marker.accuracy.horizontal} </p>
        </Popup>
      ) : null}
      {marker?.accuracy ? (
        <Source
          type="geojson"
          data={createGeoJSONCircle(
            [marker.lng, marker.lat],
            marker.accuracy.horizontal,
            64
          )}
        >
          <Layer
            type="fill"
            paint={{
              "fill-color": "blue",
              "fill-opacity": 0.3,
            }}
          />
        </Source>
      ) : null}
    </>
  );
};