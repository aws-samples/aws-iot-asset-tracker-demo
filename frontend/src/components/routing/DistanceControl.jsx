import React, { useState, useEffect, useCallback, useRef } from "react";
import { Hub } from "aws-amplify/utils";
import { fetchAuthSession } from "aws-amplify/auth";
import {
  CalculateRouteCommand,
  LocationClient,
} from "@aws-sdk/client-location";
import { GeolocateControl } from "react-map-gl";
import awsmobile from "../../aws-exports";
import { DistanceButton } from "./DistanceButton";
import { UserPositionLabel } from "./UserPositionLabel";

let cachedCredentials = null;

const getCredentials = async () => {
  const session = await fetchAuthSession();
  cachedCredentials = session.credentials;
  return cachedCredentials;
};

const refreshOrInitLocationClient = async (client) => {
  const credentials = await getCredentials();
  if (!client) {
    client = new LocationClient({
      credentials,
      region: awsmobile.aws_project_region,
    });
    return client;
  }
  return client;
};

export const DistanceControl = () => {
  const locationClientRef = useRef();
  const hubRef = useRef();
  const [userLocation, setUserLocation] = useState();
  const [assetLocation, setAssetLocation] = useState();

  const onAssetTrackerUpdate = useCallback(
    async (update) => {
      const {
        payload: { data },
      } = update;
      if (!userLocation) return;
      locationClientRef.current = await refreshOrInitLocationClient(
        locationClientRef.current
      );
      try {
        const res = await locationClientRef.current.send(
          new CalculateRouteCommand({
            CalculatorName: awsmobile.geo.AmazonLocationService.routeCalculator,
            TravelMode: "Walking",
            DeparturePosition: [userLocation.lng, userLocation.lat],
            DestinationPosition: [data.lng, data.lat],
          })
        );
        setAssetLocation({
          lng: data.lng,
          lat: data.lat,
          distance: res.Summary?.Distance,
        });
      } catch (err) {
        console.error(err);
      }
    },
    [userLocation]
  );

  useEffect(() => {
    hubRef.current = Hub.listen("assetTrackerUpdates", onAssetTrackerUpdate);

    return () => hubRef.current();
  }, [userLocation]);

  return (
    <>
      <GeolocateControl
        position="top-left"
        trackUserLocation={true}
        positionOptions={{
          enableHighAccuracy: true,
        }}
        onGeolocate={(e) => {
          setUserLocation({
            lng: e.coords.longitude,
            lat: e.coords.latitude,
          });
        }}
        onTrackUserLocationStart={(e) => {
          console.log("onTrackStart", e);
        }}
      />
      {userLocation ? <UserPositionLabel position={userLocation} /> : null}
      {assetLocation ? <DistanceButton distance={assetLocation?.distance} /> : null}
    </>
  );
};
