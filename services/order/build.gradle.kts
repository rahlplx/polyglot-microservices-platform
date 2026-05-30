import org.jetbrains.kotlin.gradle.tasks.KotlinCompile
import com.google.protobuf.gradle.*

plugins {
    kotlin("jvm") version "1.9.22"
    kotlin("kapt") version "1.9.22"
    id("com.google.protobuf") version "0.9.4"
    application
}

group = "com.company.order"
version = "1.0.0-SNAPSHOT"

repositories {
    mavenCentral()
}

val kotlinCoroutinesVersion = "1.8.0"
val grpcKotlinVersion = "1.4.1"
val grpcJavaVersion = "1.62.2"
val protobufJavaVersion = "3.25.3"
val jooqVersion = "3.19.6"
val kafkaClientsVersion = "3.7.0"
val resilience4jVersion = "2.2.0"
val openTelemetryVersion = "1.36.0"
val openTelemetrySdkVersion = "1.36.0"
val openTelemetryInstrumentationVersion = "2.3.0"
val spiffeSdkVersion = "0.8.6"
val jqwikVersion = "1.8.2"
val junitVersion = "5.10.2"
val mockkVersion = "1.13.10"
val hikariVersion = "5.1.0"
val postgresDriverVersion = "42.7.2"
val slf4jVersion = "2.0.12"
val logbackVersion = "1.5.3"
val hopliteVersion = "2.7.5"
val arrowCoreVersion = "1.2.1"

dependencies {
    // Kotlin
    implementation(kotlin("stdlib"))
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:$kotlinCoroutinesVersion")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-jdk8:$kotlinCoroutinesVersion")

    // gRPC
    implementation("io.grpc:grpc-protobuf:$grpcJavaVersion")
    implementation("io.grpc:grpc-stub:$grpcJavaVersion")
    implementation("io.grpc:grpc-kotlin-stub:$grpcKotlinVersion")
    implementation("com.google.protobuf:protobuf-java:$protobufJavaVersion")
    implementation("com.google.protobuf:protobuf-kotlin:$protobufJavaVersion")
    implementation("io.grpc:grpc-netty-shaded:$grpcJavaVersion")
    implementation("javax.annotation:javax.annotation-api:1.3.2")

    // jOOQ
    implementation("org.jooq:jooq:$jooqVersion")
    implementation("org.jooq:jooq-kotlin:$jooqVersion")
    implementation("org.postgresql:postgresql:$postgresDriverVersion")
    implementation("com.zaxxer:HikariCP:$hikariVersion")

    // Kafka
    implementation("org.apache.kafka:kafka-clients:$kafkaClientsVersion")

    // Resilience4j
    implementation("io.github.resilience4j:resilience4j-circuitbreaker:$resilience4jVersion")
    implementation("io.github.resilience4j:resilience4j-retry:$resilience4jVersion")
    implementation("io.github.resilience4j:resilience4j-ratelimiter:$resilience4jVersion")
    implementation("io.github.resilience4j:resilience4j-kotlin:$resilience4jVersion")

    // OpenTelemetry
    implementation("io.opentelemetry:opentelemetry-api:$openTelemetryVersion")
    implementation("io.opentelemetry:opentelemetry-sdk:$openTelemetrySdkVersion")
    implementation("io.opentelemetry:opentelemetry-sdk-trace:$openTelemetrySdkVersion")
    implementation("io.opentelemetry:opentelemetry-sdk-metrics:$openTelemetrySdkVersion")
    implementation("io.opentelemetry:opentelemetry-exporter-otlp:$openTelemetrySdkVersion")
    implementation("io.opentelemetry:opentelemetry-exporter-logging:$openTelemetrySdkVersion")
    implementation("io.opentelemetry.semconv:opentelemetry-semconv:1.23.1-alpha")

    // SPIFFE
    implementation("io.spiffe:java-spiffe-core:$spiffeSdkVersion")
    implementation("io.spiffe:java-spiffe-provider:$spiffeSdkVersion")

    // Configuration
    implementation("com.sksamuel.hoplite:hoplite-core:$hopliteVersion")
    implementation("com.sksamuel.hoplite:hoplite-hocon:$hopliteVersion")

    // Logging
    implementation("org.slf4j:slf4j-api:$slf4jVersion")
    implementation("ch.qos.logback:logback-classic:$logbackVersion")
    implementation("net.logstash.logback:logstash-logback-encoder:7.4")

    // Functional error handling
    implementation("io.arrow-kt:arrow-core:$arrowCoreVersion")

    // Testing
    testImplementation(kotlin("test"))
    testImplementation("org.junit.jupiter:junit-jupiter-api:$junitVersion")
    testImplementation("org.junit.jupiter:junit-jupiter-engine:$junitVersion")
    testImplementation("io.mockk:mockk:$mockkVersion")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:$kotlinCoroutinesVersion")
    testImplementation("net.jqwik:jqwik:$jqwikVersion")
    testImplementation("io.grpc:grpc-testing:$grpcJavaVersion")
    testImplementation("com.h2database:h2:2.2.224")
    testImplementation("org.testcontainers:postgresql:1.19.7")
    testImplementation("org.testcontainers:junit-jupiter:1.19.7")
}

protobuf {
    protoc {
        artifact = "com.google.protobuf:protoc:$protobufJavaVersion"
    }
    plugins {
        id("grpc") {
            artifact = "io.grpc:protoc-gen-grpc-java:$grpcJavaVersion"
        }
        id("grpckt") {
            artifact = "io.grpc:protoc-gen-grpc-kotlin:$grpcKotlinVersion:jdk8@jar"
        }
    }
    generateProtoTasks {
        all().forEach {
            it.plugins {
                id("grpc")
                id("grpckt")
            }
            it.builtins {
                id("kotlin")
            }
        }
    }
}

application {
    mainClass.set("com.company.order.infrastructure.server.ApplicationKt")
}

tasks.withType<KotlinCompile> {
    kotlinOptions {
        jvmTarget = "21"
        freeCompilerArgs = listOf(
            "-Xjsr305=strict",
            "-opt-in=kotlinx.coroutines.ExperimentalCoroutinesApi",
            "-opt-in=kotlin.RequiresOptIn"
        )
    }
}

tasks.test {
    useJUnitPlatform {
        includeEngines("junit-jupiter", "jqwik")
    }
    maxParallelForks = Runtime.getRuntime().availableProcessors().coerceAtMost(4)
}

kotlin {
    jvmToolchain(21)
}

// jOOQ code generation configuration
tasks.register("generateJooq") {
    group = "build"
    description = "Generate jOOQ code from database schema"
    doLast {
        logger.lifecycle("jOOQ code generation should be run via Flyway + jOOQ gradle plugin in CI. See Makefile.")
    }
}
