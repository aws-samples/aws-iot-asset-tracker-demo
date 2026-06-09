// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

import { Hub } from "aws-amplify/utils";
import { generateClient } from "aws-amplify/api";
import { onGeofenceEvent, onUpdatePosition } from "../common/subscriptions";

const client = generateClient();

/**
 * Handler for position updates coming from the AppSync subscription
 */
const handlePositionUpdate = ({ data }) => {
  const { onUpdatePosition } = data;
  console.debug("Position update received", onUpdatePosition);
  const { lng, lat, accuracy, sampleTime, metadata } = onUpdatePosition;
  Hub.dispatch("assetTrackerUpdates", {
    event: "positionUpdate",
    data: { lng, lat, accuracy, sampleTime, metadata },
  });
};

/**
 * Handler for geofence updates coming from the AppSync subscription
 */
const handleGeofenceEvent = ({ data }) => {
  const { onGeofenceEvent } = data;
  console.debug("Geofence update received", onGeofenceEvent);
  Hub.dispatch("assetTrackerUpdates", {
    event: "geofenceUpdate",
    data: onGeofenceEvent,
  });
};

/**
 * Helper function to unsubscribe from the AppSync subscriptions
 */
const unsubscribe = (subscriptionsRef) => {
  subscriptionsRef.current?.positionUpdates?.unsubscribe();
  console.info("Unsubscribed from onUpdatePosition AppSync mutation");
  subscriptionsRef.current?.geofencesUpdates?.unsubscribe();
  console.info("Unsubscribed from onGeofenceEvent AppSync mutation");
};

/**
 * Helper function to subscribe from the AppSync subscriptions
 */
const subscribe = (subscriptionsRef, setError) => {
  subscriptionsRef.current.positionUpdates = client
    .graphql({ query: onUpdatePosition })
    .subscribe({
      next: handlePositionUpdate,
      error: (err) => {
        console.error(err);
        setError(err);
      },
    });
  console.info("Subscribed to onUpdatePosition AppSync mutation");

  subscriptionsRef.current.geofencesUpdates = client
    .graphql({ query: onGeofenceEvent })
    .subscribe({
      next: handleGeofenceEvent,
      error: (err) => console.error(err),
    });
  console.info("Subscribed to onGeofenceEvent AppSync mutation");
};

export { subscribe, unsubscribe };
