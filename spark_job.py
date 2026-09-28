from pathlib import Path
from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F

BASE = Path(__file__).resolve().parent
INPUT = str(BASE / "data" / "processed_traffic.csv")
LOCAL_OUT = str(BASE / "data" / "spark_analytics_parquet")
HDFS_OUT = "hdfs://localhost:9000/big_data_time_machine/analytics"

spark = (
    SparkSession.builder
    .appName("BigDataTimeMachine")
    .getOrCreate()
)

df = (
    spark.read
    .option("header", True)
    .option("inferSchema", True)
    .csv(INPUT)
)

df = df.withColumn("DateTime", F.to_timestamp("DateTime"))

w = Window.partitionBy("Junction").orderBy("DateTime")

analytics = (
    df
    .withColumn("PreviousVehicles", F.lag("Vehicles").over(w))
    .withColumn(
        "VehicleChangePct",
        F.when(
            F.col("PreviousVehicles").isNull() | (F.col("PreviousVehicles") == 0),
            F.lit(None)
        ).otherwise(
            F.round(
                (F.col("Vehicles") - F.col("PreviousVehicles"))
                / F.col("PreviousVehicles") * 100,
                2
            )
        )
    )
    .withColumn(
        "UnusualChange",
        F.when(F.abs(F.col("VehicleChangePct")) >= 50, F.lit(True)).otherwise(F.lit(False))
    )
)

analytics.write.mode("overwrite").parquet(LOCAL_OUT)

# Optional HDFS output. If Hadoop is not installed/running, the local output above
# still succeeds and the error is printed instead of stopping the project.
try:
    analytics.write.mode("overwrite").parquet(HDFS_OUT)
    print("HDFS analytics written to:", HDFS_OUT)
except Exception as exc:
    print("HDFS output skipped:", exc)

print("Spark analytics written to:", LOCAL_OUT)
spark.stop()
