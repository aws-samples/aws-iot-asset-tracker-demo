import { Stack, StackProps, Duration } from "aws-cdk-lib";
import { Construct } from "constructs";
import { Policy, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { NodejsFunction } from "aws-cdk-lib/aws-lambda-nodejs";
import { RetentionDays } from "aws-cdk-lib/aws-logs";

interface FunctionsConstructProps extends StackProps {}

export class FunctionsConstruct extends Construct {
  certificateHandlerFn: Function;
  decoderFn: Function;
  appsyncUpdatePositionFn: Function;
  appsyncSendGeofenceEventFn: Function;
  appsyncTrackerHistoryFn: Function;

  constructor(scope: Construct, id: string, _props: FunctionsConstructProps) {
    super(scope, id);

    const sharedConfig = {
      handler: "handler",
      runtime: Runtime.NODEJS_18_X,
      bundling: {
        minify: true,
        target: "es2020",
        sourceMap: true,
      },
      logRetention: RetentionDays.ONE_DAY,
      timeout: Duration.seconds(30),
    };

    this.certificateHandlerFn = new NodejsFunction(this, "certificateHandler", {
      entry: "lib/fns/certificate-handler/src/index.ts",
      ...sharedConfig,
    });
    this.certificateHandlerFn.role?.attachInlinePolicy(
      new Policy(this, "certificateHandlerPolicy", {
        statements: [
          new PolicyStatement({
            actions: [
              "secretsmanager:CreateSecret",
              "secretsmanager:DeleteSecret",
            ],
            resources: [
              `arn:aws:secretsmanager:${Stack.of(this).region}:${
                Stack.of(this).account
              }:secret:assettracker/iot-cert-??????`,
            ],
          }),
          new PolicyStatement({
            actions: ["iot:CreateKeysAndCertificate"],
            resources: [`*`],
          }),
          new PolicyStatement({
            actions: ["iot:UpdateCertificate", "iot:DeleteCertificate"],
            resources: [
              `arn:aws:iot:${Stack.of(this).region}:${
                Stack.of(this).account
              }:cert/*`,
            ],
          }),
        ],
      })
    );

    this.decoderFn = new NodejsFunction(this, "decoderFn", {
      entry: "lib/fns/decoder-function/index.ts",
      environment: {
        TRACKER_NAME: "AssetTracker",
        NODE_OPTIONS: "--enable-source-maps",
      },
      memorySize: 256,
      ...sharedConfig,
    });
    this.decoderFn.role?.attachInlinePolicy(
      new Policy(this, "trackerUpdatePolicy", {
        statements: [
          new PolicyStatement({
            actions: ["geo:BatchUpdateDevicePosition"],
            resources: [
              `arn:aws:geo:${Stack.of(this).region}:${
                Stack.of(this).account
              }:tracker/AssetTracker`,
            ],
          }),
        ],
      })
    );

    this.appsyncUpdatePositionFn = new NodejsFunction(
      this,
      "appsyncUpdatePositionFn",
      {
        entry: "lib/fns/appsync-update-position/src/index.ts",
        environment: {
          NODE_OPTIONS: "--enable-source-maps",
        },
        memorySize: 256,
        ...sharedConfig,
      }
    );

    this.appsyncSendGeofenceEventFn = new NodejsFunction(
      this,
      "appsyncSendGeofenceEventFn",
      {
        entry: "lib/fns/appsync-send-geofence-event/src/index.ts",
        environment: {
          NODE_OPTIONS: "--enable-source-maps",
        },
        memorySize: 256,
        ...sharedConfig,
      }
    );

    this.appsyncTrackerHistoryFn = new NodejsFunction(
      this,
      "appsyncTrackerHistoryFn",
      {
        entry: "lib/fns/appsync-tracker-history/index.ts",
        environment: {
          TRACKER_NAME: "AssetTracker",
          NODE_OPTIONS: "--enable-source-maps",
        },
        memorySize: 256,
        ...sharedConfig,
      }
    );
    this.appsyncTrackerHistoryFn.role?.attachInlinePolicy(
      new Policy(this, "trackerGetPositionPolicy", {
        statements: [
          new PolicyStatement({
            actions: ["geo:GetDevicePositionHistory"],
            resources: [
              `arn:aws:geo:${Stack.of(this).region}:${
                Stack.of(this).account
              }:tracker/AssetTracker`,
            ],
          }),
        ],
      })
    );
  }
}
