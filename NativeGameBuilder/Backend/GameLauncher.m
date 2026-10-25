// A portable game's writable state never lives inside its signed bundle.
#import <Foundation/Foundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static void setpath(const char *key, NSString *value) {
    setenv(key, value.fileSystemRepresentation, 1);
}
int main(int argc, char **argv) {
    @autoreleasepool {
        NSBundle *bundle = NSBundle.mainBundle;
        NSString *identifier = bundle.infoDictionary[@"NXGameID"];
        if (!identifier.length || !bundle.resourcePath) return 1;
        NSFileManager *fm = NSFileManager.defaultManager;
        NSString *data = [bundle.resourcePath stringByAppendingPathComponent:@"Game"];
        NSString *support = NSSearchPathForDirectoriesInDomains(NSApplicationSupportDirectory, NSUserDomainMask, YES).firstObject;
        NSString *state = [[support stringByAppendingPathComponent:@"NXNative"] stringByAppendingPathComponent:identifier];
        NSDictionary<NSString *, NSString *> *paths = @{
            @"DM_ROOT": state,
            @"DM_SAVE": [state stringByAppendingPathComponent:@"save"],
            @"DM_TEMP": [state stringByAppendingPathComponent:@"temp"],
            @"DM_PSO_USER": [state stringByAppendingPathComponent:@"pso_user.tsv"],
            @"DM_ROMFS": [data stringByAppendingPathComponent:@"romfs"],
            @"DM_FONT_DIR": [data stringByAppendingPathComponent:@"font"],
            @"DM_MSL_DIR": [data stringByAppendingPathComponent:@"shaders"],
            @"DM_AOC_DIR": [data stringByAppendingPathComponent:@"aoc"],
            @"DM_NVN_SHMAP": [data stringByAppendingPathComponent:@"profile/shader_map.tsv"]
        };
        if (argc == 2 && !strcmp(argv[1], "--inspect")) {
            NSData *json = [NSJSONSerialization dataWithJSONObject:paths options:NSJSONWritingPrettyPrinted error:nil];
            fwrite(json.bytes, 1, json.length, stdout);
            return 0;
        }
        NSError *error = nil;
        for (NSString *name in @[@"", @"save", @"temp"]) {
            if (![fm createDirectoryAtPath:[state stringByAppendingPathComponent:name] withIntermediateDirectories:YES attributes:nil error:&error]) {
                NSLog(@"Cannot create game state directory: %@", error); return 1;
            }
        }
        NSString *log = [state stringByAppendingPathComponent:@"log.txt"];
        NSString *previous = [state stringByAppendingPathComponent:@"log.prev.txt"];
        [fm removeItemAtPath:previous error:nil];
        if ([fm fileExistsAtPath:log]) [fm moveItemAtPath:log toPath:previous error:nil];
        if (!freopen(log.fileSystemRepresentation, "a", stdout) || !freopen(log.fileSystemRepresentation, "a", stderr)) return 1;
        setvbuf(stdout, NULL, _IOLBF, 0); setvbuf(stderr, NULL, _IOLBF, 0);
        for (NSString *key in paths) setpath(key.UTF8String, paths[key]);
        // A prewarm override from a developer shell must not escape the bundle.
        unsetenv("DM_PSO_MANIFEST");
        setenv("DM_WINDOW", "1", 1);
        setenv("DM_AUDIO", "1", 0);
        setenv("DM_PRESENT_LINK", "1", 0);
        setenv("DM_PRESENT_FIFO", "1", 0);
        setenv("DM_METAL_HUD", "0", 0);
        setenv("DM_LANG", [bundle.infoDictionary[@"NXLanguage"] ?: @"en-US" UTF8String], 0);
        if (chdir(data.fileSystemRepresentation)) { perror("chdir Game resources"); return 1; }
        NSString *host = [[bundle.bundlePath stringByAppendingPathComponent:@"Contents/MacOS"] stringByAppendingPathComponent:@"dmhost"];
        NSString *modules = [data stringByAppendingPathComponent:@"modules"];
        char *const args[] = {(char *)host.fileSystemRepresentation, (char *)modules.fileSystemRepresentation, NULL};
        execv(host.fileSystemRepresentation, args);
        perror("execv dmhost");
        return 1;
    }
}
