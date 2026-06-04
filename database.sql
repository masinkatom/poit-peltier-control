CREATE DATABASE IF NOT EXISTS PELTIER_CONTROL;
USE PELTIER_CONTROL;

-- 1. Create parent table (Measurement)
CREATE TABLE IF NOT EXISTS Measurement (
    id INT AUTO_INCREMENT PRIMARY KEY,
    start_timestamp DATETIME NOT NULL,
    end_timestamp DATETIME DEFAULT NULL
);

-- 2. Create child table (Telemetry) with Foreign Key link
CREATE TABLE IF NOT EXISTS Telemetry (
    id INT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    system_state VARCHAR(50),
    temperature FLOAT,
    setpoint FLOAT,
    peltier_pwm INT,
    kp FLOAT,
    ki FLOAT,
    id_measurement INT,
    FOREIGN KEY (id_measurement) REFERENCES Measurement(id) ON DELETE CASCADE
);